"""Shared plumbing for tools: running as the member and turning errors into messages."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from fastmcp.exceptions import ToolError

from docmost_mcp_remote.auth import current_member_id
from docmost_mcp_remote.docmost import DocmostBackend, DocmostError
from docmost_mcp_remote.docmost.models import Label, Page
from docmost_mcp_remote.docmost.version import Version
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
        if str(exc).startswith("Cannot POST"):
            # Nest's answer for an endpoint this Docmost release does not have.
            raise ToolError(
                "This Docmost version does not offer this; ask the Docmost admin to upgrade."
            ) from None
        # Docmost error messages are short and contain no secrets or content.
        raise ToolError(f"Docmost: {exc}") from None


#: Seconds a Docmost version is remembered. Docmost answers its version
#: endpoint slowly, because it also asks GitHub for the latest release.
VERSION_TTL = 600.0
_version_cache: dict[str, tuple[float, Version | None]] = {}


async def docmost_version(backend: DocmostBackend) -> Version | None:
    """The Docmost version, remembered for a while; None when Docmost does not say."""
    cached = _version_cache.get("version")
    if cached is not None and time.monotonic() - cached[0] < VERSION_TTL:
        return cached[1]
    version = (await backend.version()).version
    _version_cache["version"] = (time.monotonic(), version)
    return version


async def require_version(backend: DocmostBackend, minimum: Version) -> None:
    """Refuse when Docmost is known to be older than ``minimum``.

    An unknown version is let through: an endpoint Docmost does not have
    answers with an error that ``as_member`` explains the same way.
    """
    version = await docmost_version(backend)
    if version is not None and version < minimum:
        raise ToolError(
            f"This needs Docmost {minimum} or newer and this Docmost runs {version}; "
            "ask the Docmost admin to upgrade."
        )


def formatting_hint(losses: list[str]) -> str | None:
    """Advice for a page whose formatting Markdown cannot hold; None when it can."""
    if not losses:
        return None
    return (
        f"This page has {', '.join(losses)}, which Markdown cannot hold. Appending and "
        "prepending keep them, but replacing the body or a section with Markdown removes "
        "them from the whole page. To change existing text here, read the page with "
        "get_page format='json' and write it with replace_page_json."
    )


def page_link(docmost_base: str, page: Page) -> str | None:
    """The page's address in the Docmost web app."""
    if page.space is None or not page.space.slug:
        return None
    return f"{docmost_base}/s/{page.space.slug}/p/{page.slug_id}"


_MAX_LABEL_PAGES = 10


async def all_labels(backend: DocmostBackend) -> list[Label]:
    found: list[Label] = []
    cursor: str | None = None
    for _ in range(_MAX_LABEL_PAGES):
        result = await backend.labels(cursor=cursor, limit=100)
        found.extend(result.items)
        if not result.has_next_page or not result.next_cursor:
            break
        cursor = result.next_cursor
    return found
