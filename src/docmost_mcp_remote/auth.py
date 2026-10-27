"""Who is behind the current MCP request. Tokens are checked in ``oauth.py``."""

from __future__ import annotations

import uuid

from fastmcp.server.dependencies import get_access_token


def current_member_id() -> uuid.UUID:
    """The member behind the current MCP request."""
    token = get_access_token()
    if token is None or "member_id" not in token.claims:
        raise PermissionError("request is not authenticated")
    return uuid.UUID(str(token.claims["member_id"]))


def current_grant_id() -> uuid.UUID:
    """The grant (personal token or OAuth client) behind the current MCP request."""
    token = get_access_token()
    if token is None or "grant_id" not in token.claims:
        raise PermissionError("request is not authenticated")
    return uuid.UUID(str(token.claims["grant_id"]))


def current_scopes() -> frozenset[str]:
    token = get_access_token()
    return frozenset(token.scopes) if token else frozenset()
