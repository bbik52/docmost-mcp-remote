"""Read-only tools (scope ``read``)."""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.server.auth import require_scopes
from pydantic import Field

from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.docmost import DocmostBackend
from docmost_mcp_remote.docmost.models import PageSummary
from docmost_mcp_remote.members import MemberService
from docmost_mcp_remote.tools.common import as_member, page_link
from docmost_mcp_remote.tools.spaces import SpacePolicy
from docmost_mcp_remote.tools.untrusted import NOTICE, truncate, wrap

_READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
_TAGS = re.compile(r"<[^>]+>")
_SLUG_ID = re.compile(r"^[A-Za-z0-9]{10}$")

Cursor = Annotated[
    str | None, Field(description="Value of next_cursor from a previous call, to get more items.")
]
Limit = Annotated[int, Field(ge=1, le=100, description="Maximum number of items to return.")]


def page_ref(value: str) -> str:
    """Accept a page id, its short slug id, or a Docmost page URL."""
    value = value.strip()
    if "/" in value:
        last = value.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0].split("#", 1)[0]
        candidate = last.rsplit("-", 1)[-1]
        if _SLUG_ID.match(candidate):
            return candidate
    return value


def _summary(page: PageSummary) -> dict[str, Any]:
    return {
        "id": page.id,
        "slug_id": page.slug_id,
        "title": page.title or "(untitled)",
        "space_id": page.space_id,
        "parent_page_id": page.parent_page_id,
        "has_children": page.has_children,
        "updated_at": page.updated_at.isoformat() if page.updated_at else None,
    }


def register(mcp: FastMCP, settings: Settings, members: MemberService) -> None:
    policy = SpacePolicy(settings.allowed_spaces)
    docmost_base = str(settings.docmost_url).rstrip("/")

    @mcp.tool(
        name="list_spaces",
        description="List the Docmost spaces you can access, with your role in each.",
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def list_spaces(cursor: Cursor = None, limit: Limit = 50) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            result = await backend.list_spaces(cursor=cursor, limit=limit)
            return {
                "spaces": [
                    {
                        "id": space.id,
                        "name": space.name,
                        "slug": space.slug,
                        "description": space.description or None,
                        "your_role": space.member_role,
                    }
                    for space in result.items
                    if policy.allows_space(space)
                ],
                "next_cursor": result.next_cursor if result.has_next_page else None,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="get_space",
        description=(
            "Details of one space: name, description, visibility, number of members and your "
            "role in it."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def get_space(
        space_id: Annotated[str, Field(description="Space id from list_spaces.")],
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            await policy.check(backend, space_id)
            space = await backend.get_space(space_id)
            return {
                "id": space.id,
                "name": space.name,
                "slug": space.slug,
                "description": space.description or None,
                "visibility": space.visibility,
                "member_count": space.member_count,
                "your_role": space.member_role,
                "created_at": space.created_at.isoformat() if space.created_at else None,
                "url": f"{docmost_base}/s/{space.slug}" if space.slug else None,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="list_pages",
        description=(
            "List pages of a space as a tree, one level at a time: without parent_page_id the "
            "top-level pages, with it the children of that page. has_children tells whether a "
            "page has children to list next."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def list_pages(
        space_id: Annotated[str, Field(description="Space id from list_spaces.")],
        parent_page_id: Annotated[
            str | None, Field(description="List the children of this page.")
        ] = None,
        cursor: Cursor = None,
        limit: Limit = 50,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            await policy.check(backend, space_id)
            result = await backend.list_pages(
                space_id, parent_page_id=parent_page_id, cursor=cursor, limit=limit
            )
            return {
                "pages": [_summary(page) for page in result.items],
                "next_cursor": result.next_cursor if result.has_next_page else None,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="recent_pages",
        description="List recently updated pages, newest first, in one space or in all spaces.",
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def recent_pages(
        space_id: Annotated[str | None, Field(description="Only pages in this space.")] = None,
        cursor: Cursor = None,
        limit: Limit = 20,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            allowed = await policy.allowed_ids(backend)
            if space_id:
                policy.ensure(allowed, space_id)
            result = await backend.recent_pages(space_id=space_id, cursor=cursor, limit=limit)
            return {
                "pages": [
                    _summary(page)
                    for page in result.items
                    if allowed is None or page.space_id in allowed
                ],
                "next_cursor": result.next_cursor if result.has_next_page else None,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="get_page",
        description=(
            "Read one page: its title, location and body as Markdown. Accepts a page id, the "
            "short slug id, or a Docmost page URL. Very long bodies are truncated; "
            "truncated tells when that happened."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def get_page(
        page: Annotated[str, Field(description="Page id, slug id or Docmost page URL.")],
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await backend.get_page(page_ref(page))
            await policy.check(backend, found.space_id)
            trail = await backend.breadcrumbs(found.id)
            body, truncated = truncate(found.content, settings.max_page_chars)
            return {
                "id": found.id,
                "slug_id": found.slug_id,
                "title": found.title or "(untitled)",
                "space": found.space.model_dump() if found.space else {"id": found.space_id},
                "path": [item.title or "(untitled)" for item in trail[:-1]],
                "parent_page_id": found.parent_page_id,
                "url": page_link(docmost_base, found),
                "created_at": found.created_at.isoformat() if found.created_at else None,
                "updated_at": found.updated_at.isoformat() if found.updated_at else None,
                "created_by": found.creator.name if found.creator else None,
                "last_updated_by": found.last_updated_by.name if found.last_updated_by else None,
                "you_can_edit": found.can_edit,
                "in_trash": found.deleted_at is not None,
                "notice": NOTICE,
                "content": wrap(body, source=f"page {found.id}"),
                "content_chars": len(found.content),
                "truncated": truncated,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="search",
        description=(
            "Full-text search over page titles and bodies you can access. Returns matching "
            "pages with a short snippet; use get_page to read one."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def search(
        query: Annotated[str, Field(min_length=1, max_length=500, description="Search words.")],
        space_id: Annotated[str | None, Field(description="Only search this space.")] = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            allowed = await policy.allowed_ids(backend)
            if space_id:
                policy.ensure(allowed, space_id)
            hits = await backend.search(query, space_id=space_id, limit=limit)
            return {
                "notice": NOTICE,
                "results": [
                    {
                        "id": hit.id,
                        "slug_id": hit.slug_id,
                        "title": hit.title or "(untitled)",
                        "space": hit.space.model_dump() if hit.space else {"id": hit.space_id},
                        "snippet": wrap(
                            _TAGS.sub("", hit.highlight or ""), source=f"page {hit.id}"
                        ),
                    }
                    for hit in hits
                    if allowed is None or hit.space_id in allowed
                ],
            }

        return await as_member(members, action)

    @mcp.tool(
        name="list_comments",
        description=("List the comments on a page, oldest first. Replies carry parent_comment_id."),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def list_comments(
        page_id: Annotated[str, Field(description="Page id or slug id.")],
        cursor: Cursor = None,
        limit: Limit = 50,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            ref = page_ref(page_id)
            if policy.restricted:
                found = await backend.get_page(ref)
                await policy.check(backend, found.space_id)
                ref = found.id
            result = await backend.list_comments(ref, cursor=cursor, limit=limit)
            return {
                "notice": NOTICE,
                "comments": [
                    {
                        "id": comment.id,
                        "parent_comment_id": comment.parent_comment_id,
                        "author": comment.creator.name if comment.creator else None,
                        "created_at": comment.created_at.isoformat()
                        if comment.created_at
                        else None,
                        "resolved": comment.resolved_at is not None,
                        "text": wrap(comment.text, source=f"comment {comment.id}"),
                    }
                    for comment in result.items
                ],
                "next_cursor": result.next_cursor if result.has_next_page else None,
            }

        return await as_member(members, action)
