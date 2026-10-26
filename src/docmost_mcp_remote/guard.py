"""Per-member rate limit and audit log around every tool call and resource read."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import mcp.types as mt
from fastmcp.exceptions import ResourceError, ToolError
from fastmcp.resources import ResourceResult
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult

from docmost_mcp_remote.db.admin_store import AuditStore
from docmost_mcp_remote.ratelimit import RateLimiter
from docmost_mcp_remote.tools.read import page_ref
from docmost_mcp_remote.tools.resources import page_from_uri

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

    async def _record(
        self, tool: str, page_id: str | None, space_id: str | None, outcome: str, started: float
    ) -> None:
        try:
            await self._audit.record(
                member_id=_claim("member_id"),
                grant_id=_claim("grant_id"),
                tool=tool,
                page_id=page_id[:64] if page_id else None,
                space_id=space_id,
                outcome=outcome,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception:
            logger.exception("Could not write the audit log")

    async def on_read_resource(
        self,
        context: MiddlewareContext[mt.ReadResourceRequestParams],
        call_next: CallNext[mt.ReadResourceRequestParams, ResourceResult],
    ) -> ResourceResult:
        """Resource reads count like tool calls: same budget, logged as ``read_resource``."""
        member_id = _claim("member_id")
        page_id = page_from_uri(str(context.message.uri))
        started = time.monotonic()
        if member_id is not None and not self.limiter.hit(str(member_id)):
            await self._record("read_resource", page_id, None, "rate_limited", started)
            raise ResourceError("Too many requests. Wait a minute and try again.")
        try:
            result = await super().on_read_resource(context, call_next)
        except Exception:
            await self._record("read_resource", page_id, None, "error", started)
            raise
        await self._record("read_resource", page_id, None, "ok", started)
        return result

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        member_id = _claim("member_id")
        arguments = context.message.arguments or {}
        started = time.monotonic()

        async def record(outcome: str) -> None:
            await self._record(
                context.message.name,
                _identifier(arguments, _PAGE_ARGUMENTS),
                _identifier(arguments, ("space_id",)),
                outcome,
                started,
            )

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


CATALOG_NOTE = (
    "This instance only lists the tools. Deploy docmost-mcp-remote next to your Docmost "
    "and connect to it to use them: https://github.com/bbik52/docmost-mcp-remote"
)


class CatalogOnly(Middleware):
    """Answers every tool call and resource read of the catalog with how to deploy."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        raise ToolError(CATALOG_NOTE)

    async def on_read_resource(
        self,
        context: MiddlewareContext[mt.ReadResourceRequestParams],
        call_next: CallNext[mt.ReadResourceRequestParams, ResourceResult],
    ) -> ResourceResult:
        raise ResourceError(CATALOG_NOTE)
