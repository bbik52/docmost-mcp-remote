"""Finding things quickly: name suggestions and a whole page tree in one call."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.server.auth import require_scopes
from pydantic import Field

from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.docmost import DocmostBackend
from docmost_mcp_remote.docmost.models import PageSummary
from docmost_mcp_remote.members import MemberService
from docmost_mcp_remote.tools.common import as_member
from docmost_mcp_remote.tools.spaces import SpacePolicy

_READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
#: Docmost pages per tree level request, and parallel requests per level.
_LEVEL_PAGE = 100
_PARALLEL = 8
#: Pages of one parent the tree walk reads at most (so 1000 children).
_MAX_LEVEL_REQUESTS = 10


def register(mcp: FastMCP, settings: Settings, members: MemberService) -> None:
    policy = SpacePolicy(settings.allowed_spaces)

    @mcp.tool(
        name="suggest",
        description=(
            "Quick lookup by name, as Docmost's own search box and @-mentions do: pages whose "
            "title matches, and optionally people and groups. Faster than search and good for "
            "finding a page id or a person's id from a part of a name."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def suggest(
        query: Annotated[str, Field(min_length=1, max_length=100)],
        pages: bool = True,
        people: bool = False,
        groups: bool = False,
        space_id: Annotated[str | None, Field(description="Only pages in this space.")] = None,
        limit: Annotated[int, Field(ge=1, le=25, description="Matches of each kind.")] = 10,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            allowed = await policy.allowed_ids(backend)
            if space_id:
                policy.ensure(allowed, space_id)
            found = await backend.suggest(
                query, pages=pages, users=people, groups=groups, space_id=space_id, limit=limit
            )
            result: dict[str, Any] = {}
            if pages:
                result["pages"] = [
                    {
                        "id": page.id,
                        "slug_id": page.slug_id,
                        "title": page.title or "(untitled)",
                        "space": page.space.model_dump() if page.space else {"id": page.space_id},
                    }
                    for page in found.pages
                    if allowed is None or page.space_id in allowed
                ]
            if people:
                result["people"] = [user.model_dump() for user in found.users]
            if groups:
                result["groups"] = [group.model_dump() for group in found.groups]
            return result

        return await as_member(members, action)

    @mcp.tool(
        name="get_page_tree",
        description=(
            "The page tree of a space, or of one page, several levels deep in one call. The "
            "walk stops at max_depth levels or max_pages pages; pages whose children were not "
            "read are listed in not_expanded, and get_page_tree with that page as root_page_id "
            "continues there."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def get_page_tree(
        space_id: Annotated[str, Field(description="Space id from list_spaces.")],
        root_page_id: Annotated[
            str | None, Field(description="Start below this page instead of the space's top.")
        ] = None,
        max_depth: Annotated[int, Field(ge=1, le=10)] = 3,
        max_pages: Annotated[int, Field(ge=1, le=1000)] = 300,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            await policy.check(backend, space_id)
            limiter = asyncio.Semaphore(_PARALLEL)

            async def children(parent: str | None) -> tuple[list[PageSummary], bool]:
                items: list[PageSummary] = []
                cursor: str | None = None
                async with limiter:
                    for _ in range(_MAX_LEVEL_REQUESTS):
                        page = await backend.list_pages(
                            space_id, parent_page_id=parent, cursor=cursor, limit=_LEVEL_PAGE
                        )
                        items.extend(page.items)
                        if not page.has_next_page or not page.next_cursor:
                            return items, False
                        cursor = page.next_cursor
                return items, True

            count = 0
            truncated = False
            not_expanded: list[str] = []

            def node(page: PageSummary) -> dict[str, Any]:
                return {
                    "id": page.id,
                    "slug_id": page.slug_id,
                    "title": page.title or "(untitled)",
                    "children": [],
                }

            top, partial = await children(root_page_id)
            if partial:
                truncated = True
            roots: list[dict[str, Any]] = []
            level: list[tuple[PageSummary, dict[str, Any]]] = []
            for page in top:
                if count >= max_pages:
                    truncated = True
                    break
                item = node(page)
                roots.append(item)
                level.append((page, item))
                count += 1

            for _depth in range(1, max_depth):
                parents = [(page, item) for page, item in level if page.has_children]
                if not parents:
                    level = []
                    break
                answers = await asyncio.gather(*(children(page.id) for page, _ in parents))
                level = []
                for (page, item), (kids, partial) in zip(parents, answers, strict=True):
                    if partial:
                        truncated = True
                    for kid in kids:
                        if count >= max_pages:
                            truncated = True
                            if page.id not in not_expanded:
                                not_expanded.append(page.id)
                            break
                        child = node(kid)
                        item["children"].append(child)
                        level.append((kid, child))
                        count += 1

            not_expanded.extend(page.id for page, _ in level if page.has_children)
            return {
                "space_id": space_id,
                "root_page_id": root_page_id,
                "pages": roots,
                "page_count": count,
                "truncated": truncated or bool(not_expanded),
                "not_expanded": not_expanded,
            }

        return await as_member(members, action)
