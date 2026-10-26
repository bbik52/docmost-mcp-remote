"""A health check of one space: stale, empty and untitled pages, duplicates, broken links."""

from __future__ import annotations

import asyncio
import re
from collections import Counter, defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.server.auth import require_scopes
from pydantic import Field

from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.docmost import DocmostBackend, DocmostError
from docmost_mcp_remote.docmost.models import PageSummary
from docmost_mcp_remote.members import MemberService
from docmost_mcp_remote.tools.common import as_member
from docmost_mcp_remote.tools.read import page_ref
from docmost_mcp_remote.tools.spaces import SpacePolicy

_READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
_PARALLEL = 8
_LIST_PAGE = 100
#: Entries returned in each list; the summary still counts all of them.
MAX_LISTED = 50
_TOP_EDITORS = 5
_MEMBER_PAGES = 10
#: Nodes that hold content without any text.
_CONTENT_NODES = {
    "image",
    "video",
    "attachment",
    "embed",
    "youtube",
    "drawio",
    "excalidraw",
    "mermaid",
    "mathBlock",
    "mathInline",
    "table",
    "mention",
    "horizontalRule",
    "subpages",
}
_PAGE_LINK = re.compile(r"/p/([A-Za-z0-9-]+)/?(?:[?#].*)?$")


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for child in node.get("content") or []:
            yield from _walk(child)


def is_empty(document: dict[str, Any]) -> bool:
    """True when a page body has no text and nothing else to show."""
    for node in _walk(document):
        if node.get("type") in _CONTENT_NODES:
            return False
        if node.get("type") == "text" and str(node.get("text") or "").strip():
            return False
    return True


def page_links(document: dict[str, Any], docmost_base: str) -> list[tuple[str, str]]:
    """Links and mentions to pages of this Docmost: (the page reference, how it appears)."""
    found: list[tuple[str, str]] = []
    for node in _walk(document):
        attrs = node.get("attrs") or {}
        if node.get("type") == "mention" and attrs.get("entityType") == "page":
            ref = attrs.get("slugId") or attrs.get("entityId")
            if ref:
                found.append((str(ref), f"@{attrs.get('label') or ref}"))
        for mark in node.get("marks") or []:
            href = str((mark.get("attrs") or {}).get("href") or "")
            if mark.get("type") != "link" or not href:
                continue
            if href.startswith(docmost_base):
                href = href[len(docmost_base) :] or "/"
            match = _PAGE_LINK.search(href)
            if href.startswith("/") and match:
                found.append((page_ref(match.group(1)), href))
    return list(dict.fromkeys(found))


def register(mcp: FastMCP, settings: Settings, members: MemberService) -> None:
    policy = SpacePolicy(settings.allowed_spaces)
    docmost_base = str(settings.docmost_url).rstrip("/")

    def link(space_slug: str | None, page: PageSummary) -> str | None:
        return f"{docmost_base}/s/{space_slug}/p/{page.slug_id}" if space_slug else None

    @mcp.tool(
        name="check_space_health",
        description=(
            "A health check of one space: pages not updated for stale_days, empty and untitled "
            "pages, pages sharing a title, links and @-mentions to pages that are gone or in "
            "Trash, and who updated most pages. It reads every page, up to max_pages, so it "
            "takes a while on large spaces. Lists hold at most 50 entries; the summary counts "
            "all."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def check_space_health(
        space_id: Annotated[str, Field(description="Space id from list_spaces.")],
        stale_days: Annotated[
            int, Field(ge=1, le=3650, description="Pages older than this count as stale.")
        ] = 180,
        max_pages: Annotated[
            int, Field(ge=1, le=1000, description="Check at most this many pages, newest first.")
        ] = 300,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            await policy.check(backend, space_id)
            space = await backend.get_space(space_id)
            pages: list[PageSummary] = []
            cursor: str | None = None
            more = True
            while more and len(pages) < max_pages:
                batch = await backend.recent_pages(
                    space_id=space_id, cursor=cursor, limit=_LIST_PAGE
                )
                pages.extend(batch.items)
                more = bool(batch.has_next_page and batch.next_cursor)
                cursor = batch.next_cursor
            truncated = more or len(pages) > max_pages
            pages = pages[:max_pages]

            known = {page.slug_id: page for page in pages} | {page.id: page for page in pages}
            limiter = asyncio.Semaphore(_PARALLEL)

            async def body(page: PageSummary) -> dict[str, Any] | None:
                async with limiter:
                    try:
                        return await backend.get_page_json(page.id)
                    except DocmostError:
                        # Moved or trashed while the check ran.
                        return None

            documents = await asyncio.gather(*(body(page) for page in pages))

            outside: dict[str, str | None] = {}

            async def problem(ref: str) -> str | None:
                """Why a linked page outside this space cannot be opened; None if it can."""
                if ref not in outside:
                    async with limiter:
                        try:
                            target = await backend.get_page(ref)
                        except DocmostError:
                            outside[ref] = "page not found or not accessible"
                        else:
                            outside[ref] = "page is in Trash" if target.deleted_at else None
                return outside[ref]

            def entry(page: PageSummary, **extra: Any) -> dict[str, Any]:
                return {
                    "id": page.id,
                    "title": page.title or "(untitled)",
                    "url": link(space.slug, page),
                    **extra,
                }

            broken: list[dict[str, Any]] = []
            empty: list[PageSummary] = []
            for page, document in zip(pages, documents, strict=True):
                if document is None:
                    continue
                if is_empty(document):
                    empty.append(page)
                for ref, shown in page_links(document, docmost_base):
                    if ref in known:
                        continue
                    reason = await problem(ref)
                    if reason:
                        broken.append(entry(page, link=shown, problem=reason))

            cutoff = datetime.now(UTC) - timedelta(days=stale_days)
            stale = sorted(
                (page for page in pages if page.updated_at and page.updated_at < cutoff),
                key=lambda page: page.updated_at or cutoff,
            )
            untitled = [page for page in pages if not (page.title or "").strip()]
            by_title: dict[str, list[PageSummary]] = defaultdict(list)
            for page in pages:
                title = (page.title or "").strip()
                if title:
                    by_title[title.casefold()].append(page)
            duplicates = [same for same in by_title.values() if len(same) > 1]

            editors = Counter(page.last_updated_by_id for page in pages if page.last_updated_by_id)
            names: dict[str, str | None] = {}
            member_cursor: str | None = None
            for _ in range(_MEMBER_PAGES if editors else 0):
                try:
                    found = await backend.workspace_members(cursor=member_cursor, limit=100)
                except DocmostError:
                    break  # Names are a nicety; ids are enough.
                names.update({member.id: member.name for member in found.items})
                if not found.has_next_page or not found.next_cursor:
                    break
                member_cursor = found.next_cursor

            return {
                "space": {"id": space.id, "name": space.name, "slug": space.slug},
                "pages_checked": len(pages),
                "truncated": truncated,
                "summary": {
                    "stale": len(stale),
                    "empty": len(empty),
                    "untitled": len(untitled),
                    "duplicate_titles": len(duplicates),
                    "broken_links": len(broken),
                },
                "stale": [
                    entry(page, updated_at=page.updated_at.date().isoformat())
                    for page in stale[:MAX_LISTED]
                    if page.updated_at
                ],
                "empty": [entry(page) for page in empty[:MAX_LISTED]],
                "untitled": [entry(page) for page in untitled[:MAX_LISTED]],
                "duplicate_titles": [
                    {"title": same[0].title, "pages": [entry(page) for page in same]}
                    for same in duplicates[:MAX_LISTED]
                ],
                "broken_links": broken[:MAX_LISTED],
                "top_editors": [
                    {"id": user_id, "name": names.get(user_id), "pages": count}
                    for user_id, count in editors.most_common(_TOP_EDITORS)
                ],
            }

        return await as_member(members, action)
