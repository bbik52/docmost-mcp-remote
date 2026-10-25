"""Shared plumbing for tools: running as the member and turning errors into messages."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastmcp.exceptions import ToolError

from docmost_mcp_remote.auth import current_member_id
from docmost_mcp_remote.docmost import DocmostBackend, DocmostError
from docmost_mcp_remote.docmost.models import Page
from docmost_mcp_remote.members import MemberService, SessionExpiredError

logger = logging.getLogger(__name__)


async def as_member[T](
    members: MemberService, action: Callable[[DocmostBackend], Awaitable[T]]
) -> T:
    """Run ``action`` in Docmost as the requesting member; errors become tool errors."""
    try:
        return await members.run(current_member_id(), action)
    except SessionExpiredError as exc:
        raise ToolError(str(exc)) from None
    except DocmostError as exc:
        # Docmost error messages are short and contain no secrets or content.
        raise ToolError(f"Docmost: {exc}") from None


def page_link(docmost_base: str, page: Page) -> str | None:
    """The page's address in the Docmost web app."""
    if page.space is None or not page.space.slug:
        return None
    return f"{docmost_base}/s/{page.space.slug}/p/{page.slug_id}"
