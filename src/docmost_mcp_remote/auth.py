"""Bearer-token authentication of MCP requests."""

from __future__ import annotations

import uuid

from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token

from docmost_mcp_remote.crypto import TOKEN_PREFIX
from docmost_mcp_remote.db.store import Store


class StoreTokenVerifier(TokenVerifier):
    """Accepts tokens issued by this server and maps them to a member and scopes."""

    def __init__(self, store: Store, base_url: str) -> None:
        super().__init__(base_url=base_url)
        self._store = store

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token.startswith(TOKEN_PREFIX) or len(token) > 200:
            return None
        owner = await self._store.find_token(token)
        if owner is None:
            return None
        return AccessToken(
            token=token,
            client_id=f"grant:{owner.grant_id}",
            scopes=sorted(owner.scopes),
            expires_at=int(owner.expires_at.timestamp()) if owner.expires_at else None,
            subject=str(owner.member_id),
            claims={"member_id": str(owner.member_id), "grant_id": str(owner.grant_id)},
        )


def current_member_id() -> uuid.UUID:
    """The member behind the current MCP request."""
    token = get_access_token()
    if token is None or "member_id" not in token.claims:
        raise PermissionError("request is not authenticated")
    return uuid.UUID(str(token.claims["member_id"]))


def current_scopes() -> frozenset[str]:
    token = get_access_token()
    return frozenset(token.scopes) if token else frozenset()
