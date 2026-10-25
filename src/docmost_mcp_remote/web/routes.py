"""Sign-in and account pages.

Plain server-rendered HTML forms. Every form carries a CSRF token that must
match the token in the signed cookie. Pages are never cached and cannot be
framed.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from importlib.resources import files
from typing import Any

from itsdangerous import BadSignature, URLSafeTimedSerializer
from jinja2 import Environment, PackageLoader, select_autoescape
from starlette.datastructures import FormData
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.crypto import constant_time_equal, derive_key
from docmost_mcp_remote.db.store import Store
from docmost_mcp_remote.members import MemberService, SignInError
from docmost_mcp_remote.ratelimit import RateLimiter

logger = logging.getLogger(__name__)

ALLOWED_SCOPES = ("read", "write", "delete")
_LOGIN_COOKIE_AGE = 60 * 60
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; form-action 'self'; "
        "frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
_STYLE = files("docmost_mcp_remote.web").joinpath("style.css").read_text()
_TOO_MANY = "Too many sign-in attempts. Wait a few minutes and try again."


def safe_next(value: str | None) -> str:
    """Only same-site relative paths are followed after sign-in."""
    if value and value.startswith("/") and not value.startswith(("//", "/\\")):
        return value
    return "/account"


class WebPages:
    def __init__(self, settings: Settings, store: Store, members: MemberService) -> None:
        self._settings = settings
        self._store = store
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
            Route("/account", self.account, methods=["GET"]),
            Route("/account/tokens", self.create_token, methods=["POST"]),
            Route("/account/grants/{grant_id}/revoke", self.revoke_grant, methods=["POST"]),
        ]

    # Rendering and cookies

    def _render(self, name: str, status: int = 200, **context: Any) -> HTMLResponse:
        html = self._templates.get_template(name).render(**context)
        return HTMLResponse(html, status_code=status, headers=_SECURITY_HEADERS)

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
            {"m": str(member.id), "c": secrets.token_urlsafe(32)},
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

    async def _account_page(
        self,
        session: dict[str, Any],
        *,
        new_token: str | None = None,
        error: str | None = None,
        status: int = 200,
    ) -> Response:
        member_id = uuid.UUID(session["m"])
        member = await self._store.get_member(member_id)
        if member is None or await self._store.member_disabled(member_id):
            return RedirectResponse("/login", status_code=303)
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
        _, token = await self._store.create_personal_token(uuid.UUID(session["m"]), name, scopes)
        logger.info(
            "Member %s created a personal token with scopes %s", session["m"], sorted(scopes)
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
