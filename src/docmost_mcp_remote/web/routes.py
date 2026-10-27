"""Sign-in, account and OAuth consent pages.

Plain server-rendered HTML forms. Every form carries a CSRF token that must
match the token in the signed cookie. Pages are never cached and cannot be
framed.
"""

from __future__ import annotations

import logging
import re
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import Any
from urllib.parse import quote, urlsplit

from itsdangerous import BadSignature, URLSafeTimedSerializer
from jinja2 import Environment, PackageLoader, select_autoescape
from mcp.server.auth.provider import AuthorizationParams, construct_redirect_uri
from mcp.shared.auth import OAuthClientInformationFull
from starlette.datastructures import FormData
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.crypto import constant_time_equal, derive_key
from docmost_mcp_remote.db.oauth_store import OAuthStore
from docmost_mcp_remote.db.store import Member, Store
from docmost_mcp_remote.members import MemberService, SignInError
from docmost_mcp_remote.oauth import CODE_TTL, CONSENT_PATH
from docmost_mcp_remote.ratelimit import RateLimiter

logger = logging.getLogger(__name__)

ALLOWED_SCOPES = ("read", "write", "delete", "admin")
_LOGIN_COOKIE_AGE = 60 * 60
#: Lifetimes a personal token can get, in days; 0 never expires.
_TOKEN_LIFETIMES = {"7": 7, "30": 30, "90": 90, "365": 365, "never": 0}
_DEFAULT_TOKEN_DAYS = 90
_CSP = (
    "default-src 'none'; style-src 'self'; form-action {form_action}; "
    "frame-ancestors 'none'; base-uri 'none'"
)
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": _CSP.format(form_action="'self'"),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
_STYLE = files("docmost_mcp_remote.web").joinpath("style.css").read_text()
_CSP_SOURCE = re.compile(r"[a-z][a-z0-9+.-]*:(//[A-Za-z0-9.\[\]:-]+)?")
_TOO_MANY = "Too many sign-in attempts. Wait a few minutes and try again."
_EXPIRED_REQUEST = (
    "This authorization request has expired or was already answered. "
    "Start the connection again from your app."
)


def safe_next(value: str | None) -> str:
    """Only same-site relative paths are followed after sign-in."""
    if value and value.startswith("/") and not value.startswith(("//", "/\\")):
        return value
    return "/account"


def _redirect_source(uri: str) -> str:
    """The CSP source that lets the consent form redirect to ``uri``.

    Browsers apply ``form-action`` to the redirect that follows a form post.
    """
    parts = urlsplit(uri)
    if parts.scheme in ("http", "https"):
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        source = f"{parts.scheme}://{host}" + (f":{parts.port}" if parts.port else "")
    else:
        source = f"{parts.scheme}:"
    # Anything else could inject directives into the policy.
    return source if _CSP_SOURCE.fullmatch(source) else ""


def _requested_scopes(client: OAuthClientInformationFull, params: AuthorizationParams) -> set[str]:
    """Scopes offered on the consent page.

    Without a ``scope`` parameter the member may grant what the client registered for.
    """
    if params.scopes:
        return set(params.scopes)
    return set(client.scope.split()) if client.scope else set(ALLOWED_SCOPES)


def _redirect_host(uri: str) -> str:
    parts = urlsplit(uri)
    return parts.netloc or f"{parts.scheme}:"


class WebPages:
    def __init__(
        self, settings: Settings, store: Store, oauth: OAuthStore, members: MemberService
    ) -> None:
        self._settings = settings
        self._store = store
        self._oauth = oauth
        self._members = members
        secret = settings.secret_key.get_secret_value()
        self._signer = URLSafeTimedSerializer(derive_key(secret, "web-cookies-v1").hex())
        secure = settings.public_url_is_https
        # The __Host- prefix makes browsers refuse the cookie unless it is Secure,
        # host-only and path=/; it is only usable over https.
        prefix = "__Host-" if secure else ""
        self._session_cookie = f"{prefix}dmr_session"
        self._login_cookie = f"{prefix}dmr_login"
        self._secure = secure
        self._session_age = settings.web_session_hours * 3600
        self.ip_limiter = RateLimiter(20, 10 * 60)
        self.email_limiter = RateLimiter(5, 15 * 60)
        self._templates = Environment(
            loader=PackageLoader("docmost_mcp_remote.web", "templates"),
            autoescape=select_autoescape(default=True),
        )

    def routes(self) -> list[Route]:
        return [
            Route("/", self.index, methods=["GET"]),
            Route("/assets/style.css", self.style, methods=["GET"]),
            Route("/login", self.login_form, methods=["GET"]),
            Route("/login", self.login_submit, methods=["POST"]),
            Route("/logout", self.logout, methods=["POST"]),
            Route("/logout/everywhere", self.logout_everywhere, methods=["POST"]),
            Route("/account", self.account, methods=["GET"]),
            Route("/account/tokens", self.create_token, methods=["POST"]),
            Route("/account/grants/{grant_id}/revoke", self.revoke_grant, methods=["POST"]),
            Route(CONSENT_PATH, self.consent_form, methods=["GET"]),
            Route(CONSENT_PATH, self.consent_submit, methods=["POST"]),
        ]

    # Rendering and cookies

    def _render(
        self, name: str, status: int = 200, *, headers: dict[str, str] | None = None, **context: Any
    ) -> HTMLResponse:
        html = self._templates.get_template(name).render(**context)
        return HTMLResponse(
            html, status_code=status, headers={**_SECURITY_HEADERS, **(headers or {})}
        )

    def _message(self, title: str, message: str, status: int) -> HTMLResponse:
        return self._render("message.html", status=status, title=title, message=message)

    def _set_cookie(self, response: Response, name: str, value: Any, max_age: int) -> None:
        response.set_cookie(
            name,
            self._signer.dumps(value),
            max_age=max_age,
            path="/",
            secure=self._secure,
            httponly=True,
            samesite="lax",
        )

    def _read_cookie(self, request: Request, name: str, max_age: int) -> dict[str, Any] | None:
        raw = request.cookies.get(name)
        if not raw:
            return None
        try:
            value = self._signer.loads(raw, max_age=max_age)
        except BadSignature:
            return None
        return value if isinstance(value, dict) else None

    def _web_session(self, request: Request) -> dict[str, Any] | None:
        return self._read_cookie(request, self._session_cookie, self._session_age)

    async def _active_member(self, session: dict[str, Any]) -> Member | None:
        """The member of a web session, unless gone, disabled, no longer allowed or signed out."""
        member_id = uuid.UUID(session["m"])
        member = await self._store.get_member(member_id)
        if (
            member is None
            or await self._store.member_disabled(member_id)
            or not self._settings.email_allowed(member.email)
        ):
            return None
        # Sessions from before this release carry no sign-in time and count as old.
        ended = member.web_sessions_after
        if ended is not None and float(session.get("t") or 0) < ended.timestamp():
            return None
        return member

    @staticmethod
    def _csrf_ok(form: FormData, expected: str | None) -> bool:
        submitted = form.get("csrf")
        return (
            isinstance(submitted, str)
            and expected is not None
            and constant_time_equal(submitted, expected)
        )

    @staticmethod
    def _client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    # Pages

    async def index(self, _: Request) -> Response:
        return RedirectResponse("/account", status_code=303)

    async def style(self, _: Request) -> Response:
        return Response(
            _STYLE, media_type="text/css", headers={"Cache-Control": "public, max-age=3600"}
        )

    def _login_page(
        self, *, next_path: str, error: str | None = None, email: str = "", status: int = 200
    ) -> HTMLResponse:
        csrf = secrets.token_urlsafe(32)
        response = self._render(
            "login.html",
            status=status,
            csrf=csrf,
            next=next_path,
            error=error,
            email=email,
            stores_password=self._settings.relogin_mode == "stored_password",
        )
        self._set_cookie(response, self._login_cookie, {"c": csrf}, _LOGIN_COOKIE_AGE)
        return response

    async def login_form(self, request: Request) -> Response:
        return self._login_page(next_path=safe_next(request.query_params.get("next")))

    async def login_submit(self, request: Request) -> Response:
        form = await request.form()
        next_path = safe_next(str(form.get("next") or ""))
        email = str(form.get("email") or "").strip()[:320]
        password = str(form.get("password") or "")
        cookie = self._read_cookie(request, self._login_cookie, _LOGIN_COOKIE_AGE)
        if not self._csrf_ok(form, cookie.get("c") if cookie else None):
            return self._login_page(
                next_path=next_path,
                error="The form expired. Please try again.",
                email=email,
                status=400,
            )
        if not self.ip_limiter.hit(self._client_ip(request)) or not self.email_limiter.hit(
            email.lower()
        ):
            return self._login_page(next_path=next_path, error=_TOO_MANY, email=email, status=429)
        try:
            member = await self._members.sign_in(email, password)
        except SignInError as exc:
            return self._login_page(next_path=next_path, error=str(exc), email=email, status=401)
        self.email_limiter.reset(email.lower())
        response = RedirectResponse(next_path, status_code=303)
        self._set_cookie(
            response,
            self._session_cookie,
            {"m": str(member.id), "c": secrets.token_urlsafe(32), "t": time.time()},
            self._session_age,
        )
        response.delete_cookie(self._login_cookie, path="/", secure=self._secure)
        return response

    async def logout(self, request: Request) -> Response:
        session = self._web_session(request)
        form = await request.form()
        response = RedirectResponse("/login", status_code=303)
        if session is not None and self._csrf_ok(form, session.get("c")):
            response.delete_cookie(self._session_cookie, path="/", secure=self._secure)
        return response

    async def logout_everywhere(self, request: Request) -> Response:
        """End the member's web sessions in every browser, this one included."""
        session = self._web_session(request)
        form = await request.form()
        response = RedirectResponse("/login", status_code=303)
        if session is not None and self._csrf_ok(form, session.get("c")):
            await self._store.end_web_sessions(uuid.UUID(session["m"]))
            logger.info("Member %s signed out everywhere", session["m"])
            response.delete_cookie(self._session_cookie, path="/", secure=self._secure)
        return response

    async def _account_page(
        self,
        session: dict[str, Any],
        *,
        new_token: str | None = None,
        error: str | None = None,
        status: int = 200,
    ) -> Response:
        member = await self._active_member(session)
        if member is None:
            return RedirectResponse("/login", status_code=303)
        member_id = member.id
        return self._render(
            "account.html",
            status=status,
            member=member,
            grants=await self._store.list_grants(member_id),
            csrf=session["c"],
            new_token=new_token,
            error=error,
            mcp_url=f"{self._settings.public_base}/mcp",
        )

    async def account(self, request: Request) -> Response:
        session = self._web_session(request)
        if session is None:
            return RedirectResponse("/login?next=/account", status_code=303)
        return await self._account_page(session)

    async def create_token(self, request: Request) -> Response:
        session = self._web_session(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        if await self._active_member(session) is None:
            return RedirectResponse("/login", status_code=303)
        form = await request.form()
        if not self._csrf_ok(form, session.get("c")):
            return await self._account_page(
                session, error="The form expired. Please try again.", status=400
            )
        name = str(form.get("name") or "").strip()[:100]
        if not name:
            return await self._account_page(session, error="Give the token a name.", status=400)
        requested = {str(value) for value in form.getlist("scope")}
        scopes = frozenset({"read"} | (requested & set(ALLOWED_SCOPES)))
        days = _TOKEN_LIFETIMES.get(str(form.get("expires") or ""), _DEFAULT_TOKEN_DAYS)
        expires_at = datetime.now(UTC) + timedelta(days=days) if days else None
        _, token = await self._store.create_personal_token(
            uuid.UUID(session["m"]), name, scopes, expires_at
        )
        logger.info(
            "Member %s created a personal token with scopes %s, expiring %s",
            session["m"],
            sorted(scopes),
            expires_at.date().isoformat() if expires_at else "never",
        )
        return await self._account_page(session, new_token=token)

    async def revoke_grant(self, request: Request) -> Response:
        session = self._web_session(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        form = await request.form()
        if not self._csrf_ok(form, session.get("c")):
            return await self._account_page(
                session, error="The form expired. Please try again.", status=400
            )
        try:
            grant_id = uuid.UUID(request.path_params["grant_id"])
        except ValueError:
            return RedirectResponse("/account", status_code=303)
        if await self._store.revoke_grant(uuid.UUID(session["m"]), grant_id):
            logger.info("Member %s revoked grant %s", session["m"], grant_id)
        return RedirectResponse("/account", status_code=303)

    # OAuth consent

    async def _pending_request(
        self, request_id: str
    ) -> tuple[OAuthClientInformationFull, AuthorizationParams] | None:
        if not request_id or len(request_id) > 200:
            return None
        pending = await self._oauth.load_request(request_id)
        if pending is None:
            return None
        client_id, params_json = pending
        info = await self._oauth.load_client(client_id)
        if info is None:
            return None
        client = OAuthClientInformationFull.model_validate_json(info)
        return client, AuthorizationParams.model_validate_json(params_json)

    async def consent_form(self, request: Request) -> Response:
        request_id = request.query_params.get("request", "")
        session = self._web_session(request)
        if session is None:
            next_path = f"{CONSENT_PATH}?request={quote(request_id, safe='')}"
            return RedirectResponse(f"/login?next={quote(next_path, safe='')}", status_code=303)
        member = await self._active_member(session)
        if member is None:
            return RedirectResponse("/login", status_code=303)
        pending = await self._pending_request(request_id)
        if pending is None:
            return self._message("Request expired", _EXPIRED_REQUEST, 400)
        client, params = pending
        redirect_uri = str(params.redirect_uri)
        csp = _CSP.format(form_action=f"'self' {_redirect_source(redirect_uri)}")
        return self._render(
            "consent.html",
            headers={"Content-Security-Policy": csp},
            member=member,
            client_name=(client.client_name or "An unnamed app")[:100],
            redirect_host=_redirect_host(redirect_uri),
            requested=_requested_scopes(client, params),
            request_id=request_id,
            csrf=session["c"],
        )

    async def consent_submit(self, request: Request) -> Response:
        session = self._web_session(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        form = await request.form()
        if not self._csrf_ok(form, session.get("c")):
            return self._message(
                "Form expired", "The form expired. Start again from your app.", 400
            )
        request_id = str(form.get("request") or "")
        pending = await self._pending_request(request_id)
        # Deleting the request makes every answer single use.
        if pending is None or not await self._oauth.delete_request(request_id):
            return self._message("Request expired", _EXPIRED_REQUEST, 400)
        member = await self._active_member(session)
        if member is None:
            return RedirectResponse("/login", status_code=303)
        member_id = member.id
        client, params = pending
        redirect_uri = str(params.redirect_uri)
        if form.get("action") != "approve":
            logger.info("Member %s denied OAuth client %s", member_id, client.client_id)
            return RedirectResponse(
                construct_redirect_uri(redirect_uri, error="access_denied", state=params.state),
                status_code=303,
                headers={"Cache-Control": "no-store"},
            )
        requested = _requested_scopes(client, params)
        ticked = {str(value) for value in form.getlist("scope")}
        scopes = frozenset({"read"} | (ticked & requested & set(ALLOWED_SCOPES)))
        if client.client_id is None:
            return self._message("Request expired", _EXPIRED_REQUEST, 400)
        code = await self._oauth.create_grant_with_code(
            member_id=member_id,
            client_id=client.client_id,
            client_name=client.client_name or client.client_id,
            scopes=scopes,
            code_challenge=params.code_challenge,
            redirect_uri=redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
            ttl=CODE_TTL,
        )
        logger.info(
            "Member %s allowed OAuth client %s with scopes %s",
            member_id,
            client.client_id,
            sorted(scopes),
        )
        return RedirectResponse(
            construct_redirect_uri(redirect_uri, code=code, state=params.state),
            status_code=303,
            headers={"Cache-Control": "no-store"},
        )
