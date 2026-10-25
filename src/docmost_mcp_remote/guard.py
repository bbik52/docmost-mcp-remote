"""Per-member rate limit and audit log around every tool call."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import mcp.types as mt
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult

from docmost_mcp_remote.db.admin_store import AuditStore
from docmost_mcp_remote.ratelimit import RateLimiter
from docmost_mcp_remote.tools.read import page_ref

logger = logging.getLogger(__name__)

_PAGE_ARGUMENTS = ("page", "page_id")


def _claim(name: str) -> uuid.UUID | None:
    token = get_access_token()
    value = token.claims.get(name) if token else None
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _identifier(arguments: dict[str, Any], names: tuple[str, ...]) -> str | None:
    """A page or space id from the arguments; other arguments are never looked at."""
    for name in names:
        value = arguments.get(name)
        if isinstance(value, str) and value:
            return page_ref(value)[:64]
    return None


class ToolGuard(Middleware):
    def __init__(self, audit: AuditStore, calls_per_minute: int) -> None:
        self._audit = audit
        self.limiter = RateLimiter(calls_per_minute, 60)

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        member_id, grant_id = _claim("member_id"), _claim("grant_id")
        arguments = context.message.arguments or {}
        started = time.monotonic()

        async def record(outcome: str) -> None:
            try:
                await self._audit.record(
                    member_id=member_id,
                    grant_id=grant_id,
                    tool=context.message.name,
                    page_id=_identifier(arguments, _PAGE_ARGUMENTS),
                    space_id=_identifier(arguments, ("space_id",)),
                    outcome=outcome,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            except Exception:
                logger.exception("Could not write the audit log")

        if member_id is not None and not self.limiter.hit(str(member_id)):
            await record("rate_limited")
            raise ToolError("Too many tool calls. Wait a minute and try again.")
        try:
            result = await call_next(context)
        except Exception:
            await record("error")
            raise
        await record("error" if getattr(result, "is_error", False) else "ok")
        return result
