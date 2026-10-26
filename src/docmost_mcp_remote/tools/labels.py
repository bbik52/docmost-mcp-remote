"""Labels and backlinks (Docmost 0.90 and newer).

Labels are workspace-wide names attached to pages; adding or removing one
does not touch the page body, so no snapshot is taken.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import require_scopes
from pydantic import Field

from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.docmost import DocmostBackend
from docmost_mcp_remote.docmost.models import Label, LinkedPage, Page
from docmost_mcp_remote.docmost.version import Version
from docmost_mcp_remote.members import MemberService
from docmost_mcp_remote.tools.common import as_member, require_version
from docmost_mcp_remote.tools.read import Cursor, Limit, page_ref
from docmost_mcp_remote.tools.spaces import SpacePolicy

#: First release with labels and backlinks.
LABELS_SINCE = Version(0, 90, 0)

_READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
_WRITE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}

PageRef = Annotated[str, Field(description="Page id, slug id or Docmost page URL.")]
LabelName = Annotated[
    str,
    Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9_-][A-Za-z0-9_~-]*$",
        description="Label name: letters, digits, '-', '_' and '~'. Docmost stores it lowercase.",
    ),
]


def _label(label: Label) -> dict[str, Any]:
    return {"id": label.id, "name": label.name}


def _linked(page: LinkedPage) -> dict[str, Any]:
    return {
        "id": page.id,
        "slug_id": page.slug_id,
        "title": page.title or "(untitled)",
        "space": page.space.model_dump() if page.space else {"id": page.space_id},
        "updated_at": page.updated_at.isoformat() if page.updated_at else None,
    }


def register(mcp: FastMCP, settings: Settings, members: MemberService) -> None:
    policy = SpacePolicy(settings.allowed_spaces)

    async def load_page(backend: DocmostBackend, ref: str) -> Page:
        await require_version(backend, LABELS_SINCE)
        page = await backend.get_page(page_ref(ref))
        await policy.check(backend, page.space_id)
        return page

    @mcp.tool(
        name="list_backlinks",
        description=(
            "Pages that link to this page (incoming), or that this page links to (outgoing). "
            "Use it before moving, renaming or trashing a page. Needs Docmost 0.90 or newer."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def list_backlinks(
        page: PageRef,
        direction: Annotated[
            Literal["incoming", "outgoing"],
            Field(description="incoming: pages linking here; outgoing: pages linked from here."),
        ] = "incoming",
        cursor: Cursor = None,
        limit: Limit = 50,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            allowed = await policy.allowed_ids(backend)
            result = await backend.backlinks(found.id, direction, cursor=cursor, limit=limit)
            return {
                "page_id": found.id,
                "direction": direction,
                "pages": [
                    _linked(item)
                    for item in result.items
                    if allowed is None or item.space_id in allowed
                ],
                "next_cursor": result.next_cursor if result.has_next_page else None,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="list_labels",
        description=(
            "List labels: those of one page, or without page all labels used in the "
            "workspace. Needs Docmost 0.90 or newer."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def list_labels(
        page: Annotated[str | None, Field(description="Only the labels of this page.")] = None,
        cursor: Cursor = None,
        limit: Limit = 100,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            if page:
                found = await load_page(backend, page)
                result = await backend.page_labels(found.id, cursor=cursor, limit=limit)
            else:
                await require_version(backend, LABELS_SINCE)
                result = await backend.labels(cursor=cursor, limit=limit)
            return {
                "labels": [_label(label) for label in result.items],
                "next_cursor": result.next_cursor if result.has_next_page else None,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="find_pages_by_label",
        description=(
            "List the pages that carry a label, in all spaces or in one. Needs Docmost 0.90 "
            "or newer."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def find_pages_by_label(
        label: LabelName,
        space_id: Annotated[str | None, Field(description="Only pages in this space.")] = None,
        cursor: Cursor = None,
        limit: Limit = 50,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            await require_version(backend, LABELS_SINCE)
            allowed = await policy.allowed_ids(backend)
            if space_id:
                policy.ensure(allowed, space_id)
            result = await backend.pages_by_label(
                label.lower(), space_id=space_id, cursor=cursor, limit=limit
            )
            return {
                "label": label.lower(),
                "pages": [
                    _linked(item)
                    for item in result.items
                    if allowed is None or item.space_id in allowed
                ],
                "next_cursor": result.next_cursor if result.has_next_page else None,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="add_labels",
        description=(
            "Add labels to a page; labels that do not exist yet are created. The page body "
            "is not changed. Needs Docmost 0.90 or newer."
        ),
        annotations=_WRITE,
        auth=require_scopes("write"),
    )
    async def add_labels(
        page: PageRef,
        labels: Annotated[list[LabelName], Field(min_length=1, max_length=25)],
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            await backend.add_labels(found.id, labels)
            current = await backend.page_labels(found.id, limit=100)
            return {"page_id": found.id, "labels": [_label(item) for item in current.items]}

        return await as_member(members, action)

    @mcp.tool(
        name="remove_label",
        description=(
            "Remove a label from a page. A label no page uses any more disappears from the "
            "workspace. Needs Docmost 0.90 or newer."
        ),
        annotations=_WRITE,
        auth=require_scopes("write"),
    )
    async def remove_label(page: PageRef, label: LabelName) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            current = (await backend.page_labels(found.id, limit=100)).items
            match = next((item for item in current if item.name == label.lower()), None)
            if match is None:
                raise ToolError(f"The page has no label {label.lower()!r}.")
            await backend.remove_label(found.id, match.id)
            return {
                "page_id": found.id,
                "removed": match.name,
                "labels": [_label(item) for item in current if item.id != match.id],
            }

        return await as_member(members, action)
