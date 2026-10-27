"""OAuth 2.1 authorization server and bearer-token verification.

The server is its own authorization server, as the MCP authorization spec
describes: clients register dynamically, send the member through the
consent page (``/oauth/consent``) and exchange the code with PKCE. Personal
tokens from the account page and OAuth access tokens are checked by the same
``load_access_token``.
"""

from __future__ import annotations

import ipaddress
import logging
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from fastmcp.server.auth import AccessToken, OAuthProvider
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.crypto import TOKEN_PREFIX
from docmost_mcp_remote.db.oauth_store import OAuthStore
from docmost_mcp_remote.db.store import Store
from docmost_mcp_remote.ratelimit import RateLimiter

logger = logging.getLogger(__name__)

SCOPES = ("read", "write", "delete", "admin")
ACCESS_TOKEN_TTL = timedelta(hours=1)
REFRESH_TOKEN_TTL = timedelta(days=30)
CODE_TTL = timedelta(minutes=5)
REQUEST_TTL = timedelta(minutes=15)
CONSENT_PATH = "/oauth/consent"

#: Abuse limits for dynamic client registration. Only clients that never got a
#: grant count; at the limit the oldest of them whose consent request has
#: expired make room for new ones, so flooding cannot lock out real clients.
MAX_UNUSED_CLIENTS = 1000
MAX_REDIRECT_URIS = 10
REGISTRATIONS_PER_IP = (10, 60 * 60)

#: Schemes that must never be a redirect target.
_FORBIDDEN_SCHEMES = frozenset({"javascript", "data", "file", "vbscript", "about", "blob", "ftp"})


def redirect_uri_allowed(uri: str) -> bool:
    """https, http on a loopback address, or a private-use scheme of a native app."""
    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    if parts.fragment or not scheme:
        return False
    if scheme == "https":
        return bool(parts.hostname)
    if scheme == "http":
        host = parts.hostname or ""
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False
    return scheme not in _FORBIDDEN_SCHEMES


def _normalize_resource(value: str | None) -> str | None:
    return value.rstrip("/") if value else value


class StoredAuthorizationCode(AuthorizationCode):
    grant_id: uuid.UUID


class StoredRefreshToken(RefreshToken):
    grant_id: uuid.UUID


class _RegistrationRateLimit:
    """Limits client registrations per client IP."""

    def __init__(self, app: ASGIApp, limiter: RateLimiter) -> None:
        self._app = app
        self._limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("method") == "POST":
            client = scope.get("client")
            if not self._limiter.hit(client[0] if client else "unknown"):
                response = JSONResponse(
                    {
                        "error": "invalid_client_metadata",
                        "error_description": "Too many client registrations. Try again later.",
                    },
                    status_code=429,
                    headers={"Retry-After": "3600"},
                )
                await response(scope, receive, send)
                return
        await self._app(scope, receive, send)


class DocmostOAuthProvider(OAuthProvider):
    def __init__(self, settings: Settings, store: Store, oauth: OAuthStore) -> None:
        super().__init__(
            base_url=settings.public_base,
            service_documentation_url="https://github.com/bbik52/docmost-mcp-remote",
            client_registration_options=ClientRegistrationOptions(
                # A client may ask for every scope; the member decides on the consent page.
                enabled=True,
                valid_scopes=list(SCOPES),
                default_scopes=list(SCOPES),
            ),
            revocation_options=RevocationOptions(enabled=True),
        )
        self._settings = settings
        self._store = store
        self._oauth = oauth
        self.registration_limiter = RateLimiter(*REGISTRATIONS_PER_IP)

    @property
    def resource_url(self) -> str:
        return f"{self._settings.public_base}/mcp"

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        routes = []
        for route in super().get_routes(mcp_path):
            if route.path == "/register":
                route = Route(
                    route.path,
                    _RegistrationRateLimit(route.app, self.registration_limiter),
                    methods=sorted(route.methods or []),
                )
            routes.append(route)
        return routes

    # Clients

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if len(client_id) > 64:
            return None
        info = await self._oauth.load_client(client_id)
        return OAuthClientInformationFull.model_validate_json(info) if info else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(uri) for uri in client_info.redirect_uris or []]
        if not uris:
            raise RegistrationError(
                "invalid_redirect_uri", "At least one redirect URI is required."
            )
        if len(uris) > MAX_REDIRECT_URIS:
            raise RegistrationError(
                "invalid_redirect_uri", f"At most {MAX_REDIRECT_URIS} redirect URIs are allowed."
            )
        for uri in uris:
            if len(uri) > 2000 or not redirect_uri_allowed(uri):
                raise RegistrationError(
                    "invalid_redirect_uri",
                    "Redirect URIs must use https, http on a loopback address, "
                    "or a private-use scheme.",
                )
        if client_info.client_name and len(client_info.client_name) > 200:
            raise RegistrationError("invalid_client_metadata", "client_name is too long.")
        unused = await self._oauth.count_unused_clients()
        if unused >= MAX_UNUSED_CLIENTS:
            evicted = await self._oauth.evict_unused_clients(
                unused - MAX_UNUSED_CLIENTS + 1, REQUEST_TTL
            )
            if unused - evicted >= MAX_UNUSED_CLIENTS:
                logger.warning("Client registration refused: %d unused clients registered", unused)
                raise RegistrationError(
                    "invalid_client_metadata", "This server does not accept new clients right now."
                )
            logger.warning("Removed %d unused clients to make room for a new one", evicted)
        if client_info.client_id is None:
            raise RegistrationError("invalid_client_metadata", "Missing client id.")
        await self._oauth.save_client(client_info.client_id, client_info.model_dump_json())
        logger.info("Registered OAuth client %s", client_info.client_id)

    # Authorization

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        resource = _normalize_resource(params.resource)
        if resource is not None and resource != self.resource_url:
            raise AuthorizeError("invalid_target", "Unknown resource.")
        bound = params.model_copy(update={"resource": self.resource_url})
        if client.client_id is None:
            raise AuthorizeError("unauthorized_client", "Unknown client.")
        request_id = await self._oauth.save_request(
            client.client_id, bound.model_dump_json(), REQUEST_TTL
        )
        return f"{self._settings.public_base}{CONSENT_PATH}?request={request_id}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> StoredAuthorizationCode | None:
        if not authorization_code.startswith(TOKEN_PREFIX) or len(authorization_code) > 200:
            return None
        stored = await self._oauth.load_code(authorization_code)
        if stored is None or stored.client_id != client.client_id:
            return None
        if stored.used:
            # RFC 6749 section 4.1.2: a replayed code revokes what it issued.
            await self._revoke_grant(stored.grant_id, "authorization code replayed")
            return None
        return StoredAuthorizationCode(
            code=authorization_code,
            scopes=sorted(stored.scopes),
            expires_at=stored.expires_at.timestamp(),
            client_id=stored.client_id,
            code_challenge=stored.code_challenge,
            redirect_uri=AnyUrl(stored.redirect_uri),
            redirect_uri_provided_explicitly=stored.redirect_uri_provided_explicitly,
            resource=stored.resource,
            subject=str(stored.member_id),
            grant_id=stored.grant_id,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        if not isinstance(authorization_code, StoredAuthorizationCode):
            raise TokenError("invalid_grant", "Unknown authorization code.")
        if not await self._oauth.use_code(authorization_code.code):
            await self._revoke_grant(authorization_code.grant_id, "authorization code replayed")
            raise TokenError("invalid_grant", "Authorization code was already used.")
        return await self._issue(
            authorization_code.grant_id,
            scopes=None,
            granted=authorization_code.scopes,
            resource=authorization_code.resource,
        )

    # Refresh

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> StoredRefreshToken | None:
        if not refresh_token.startswith(TOKEN_PREFIX) or len(refresh_token) > 200:
            return None
        stored = await self._oauth.load_token(refresh_token)
        if stored is None or stored.kind != "refresh" or stored.client_id != client.client_id:
            return None
        if stored.replaced:
            await self._revoke_grant(stored.grant_id, "refresh token reused")
            return None
        return StoredRefreshToken(
            token=refresh_token,
            client_id=stored.client_id,
            scopes=sorted(stored.scopes),
            expires_at=int(stored.expires_at.timestamp()) if stored.expires_at else None,
            resource=stored.resource,
            subject=str(stored.member_id),
            grant_id=stored.grant_id,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        if not isinstance(refresh_token, StoredRefreshToken):
            raise TokenError("invalid_grant", "Unknown refresh token.")
        if not await self._oauth.replace_refresh_token(refresh_token.token):
            await self._revoke_grant(refresh_token.grant_id, "refresh token reused")
            raise TokenError("invalid_grant", "Refresh token was already used.")
        narrowed = frozenset(scopes) if set(scopes) != set(refresh_token.scopes) else None
        return await self._issue(
            refresh_token.grant_id,
            scopes=narrowed,
            granted=scopes,
            resource=refresh_token.resource,
        )

    async def _issue(
        self,
        grant_id: uuid.UUID,
        *,
        scopes: frozenset[str] | None,
        granted: list[str],
        resource: str | None,
    ) -> OAuthToken:
        issued = await self._oauth.issue_tokens(
            grant_id,
            scopes=scopes,
            resource=resource,
            access_ttl=ACCESS_TOKEN_TTL,
            refresh_ttl=REFRESH_TOKEN_TTL,
        )
        return OAuthToken(
            access_token=issued.access_token,
            token_type="Bearer",  # noqa: S106
            expires_in=int(ACCESS_TOKEN_TTL.total_seconds()),
            scope=" ".join(sorted(granted)),
            refresh_token=issued.refresh_token,
        )

    # Verification and revocation

    async def load_access_token(self, token: str) -> AccessToken | None:
        if not token.startswith(TOKEN_PREFIX) or len(token) > 200:
            return None
        owner = await self._store.find_token(token)
        if owner is None:
            return None
        if owner.kind == "access" and _normalize_resource(owner.resource) != self.resource_url:
            return None
        claims: dict[str, Any] = {
            "member_id": str(owner.member_id),
            "grant_id": str(owner.grant_id),
        }
        return AccessToken(
            token=token,
            client_id=owner.client_id or f"grant:{owner.grant_id}",
            scopes=sorted(owner.scopes),
            expires_at=int(owner.expires_at.timestamp()) if owner.expires_at else None,
            resource=owner.resource,
            subject=str(owner.member_id),
            claims=claims,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, StoredRefreshToken):
            grant_id = token.grant_id
        elif isinstance(token, AccessToken) and "grant_id" in token.claims:
            grant_id = uuid.UUID(str(token.claims["grant_id"]))
        else:
            return
        await self._oauth.revoke_grant(grant_id)
        await self._oauth.revoke_grant_tokens(grant_id)
        logger.info("Grant %s revoked by its client", grant_id)

    async def _revoke_grant(self, grant_id: uuid.UUID, reason: str) -> None:
        """Revoke a grant after a sign of token theft."""
        await self._oauth.revoke_grant(grant_id)
        await self._oauth.revoke_grant_tokens(grant_id)
        logger.warning("Revoked grant %s: %s", grant_id, reason)
