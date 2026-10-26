"""Page history tools (scope ``read``).

Docmost keeps versions of a page body as ProseMirror JSON; this server turns
them into Markdown. The conversion is close to Docmost's own Markdown but not
identical, so a diff between a version and the current body converts both
sides the same way.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import require_scopes
from pydantic import Field

from docmost_mcp_remote.auth import current_member_id
from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.db.snapshot_store import SnapshotStore
from docmost_mcp_remote.docmost import DocmostBackend, DocmostNotFoundError
from docmost_mcp_remote.docmost.models import Page
from docmost_mcp_remote.members import MemberService
from docmost_mcp_remote.sections import unified_diff
from docmost_mcp_remote.tools.common import as_member
from docmost_mcp_remote.tools.read import Cursor, Limit, page_ref
from docmost_mcp_remote.tools.spaces import SpacePolicy
from docmost_mcp_remote.tools.untrusted import NOTICE, truncate, wrap

_READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
MAX_DIFF_CHARS = 20_000
CURRENT = "current"

PageRef = Annotated[str, Field(description="Page id, slug id or Docmost page URL.")]
VersionRef = Annotated[
    str,
    Field(
        description=(
            "'current', a version id from list_page_history, or a snapshot id from list_snapshots."
        )
    ),
]


def register(
    mcp: FastMCP, settings: Settings, members: MemberService, snapshots: SnapshotStore
) -> None:
    policy = SpacePolicy(settings.allowed_spaces)

    async def load_page(backend: DocmostBackend, ref: str) -> Page:
        page = await backend.get_page(page_ref(ref))
        await policy.check(backend, page.space_id)
        return page

    @mcp.tool(
        name="list_page_history",
        description=(
            "List the versions of a page that Docmost saved, newest first, with who changed "
            "it. Docmost saves a version a few minutes after edits stop. Read one with "
            "get_page_version or compare with diff_page."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def list_page_history(
        page: PageRef, cursor: Cursor = None, limit: Limit = 20
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            result = await backend.page_history(found.id, cursor=cursor, limit=limit)
            return {
                "page_id": found.id,
                "versions": [
                    {
                        "id": entry.id,
                        "created_at": entry.created_at.isoformat() if entry.created_at else None,
                        "title": entry.title or "(untitled)",
                        "last_updated_by": entry.last_updated_by.name
                        if entry.last_updated_by
                        else None,
                        "contributors": [user.name for user in entry.contributors if user.name],
                    }
                    for entry in result.items
                ],
                "next_cursor": result.next_cursor if result.has_next_page else None,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="get_page_version",
        description=(
            "Read one saved version of a page from list_page_history, as Markdown converted "
            "by this server."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def get_page_version(
        version_id: Annotated[str, Field(description="Version id from list_page_history.")],
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            version = await backend.history_version(version_id)
            page = await load_page(backend, version.page_id)
            body, truncated = truncate(version.content, settings.max_page_chars)
            return {
                "id": version.id,
                "page_id": page.id,
                "title": version.title or "(untitled)",
                "created_at": version.created_at.isoformat() if version.created_at else None,
                "last_updated_by": version.last_updated_by.name
                if version.last_updated_by
                else None,
                "notice": NOTICE,
                "content": wrap(body, source=f"page {page.id} version {version.id}"),
                "content_chars": len(version.content),
                "truncated": truncated,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="diff_page",
        description=(
            "Show what changed in a page between two points as a unified diff: 'current', a "
            "version from list_page_history, or a snapshot from list_snapshots. By default "
            "from_version is compared with the current body."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def diff_page(
        page: PageRef, from_version: VersionRef, to_version: VersionRef = CURRENT
    ) -> dict[str, Any]:
        member_id = current_member_id()

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            refs = (from_version.strip(), to_version.strip())
            kinds = {ref: await kind(ref) for ref in refs}
            # Snapshots hold Docmost's own Markdown, versions are converted here:
            # the current body is taken in the same form as the other side.
            converted = "snapshot" not in kinds.values()

            async def body(ref: str) -> str:
                if kinds[ref] == CURRENT:
                    if converted:
                        return await backend.get_page_document(found.id)
                    return found.content
                if kinds[ref] == "snapshot":
                    snapshot = await snapshots.load(member_id, uuid.UUID(ref))
                    if snapshot is None or snapshot.info.page_id != found.id:
                        raise ToolError(f"Snapshot {ref} is not a snapshot of this page.")
                    return snapshot.content
                try:
                    version = await backend.history_version(ref)
                except DocmostNotFoundError:
                    raise ToolError(f"Version {ref} not found.") from None
                if version.page_id != found.id:
                    raise ToolError(f"Version {ref} is not a version of this page.")
                return version.content

            before, after = await body(refs[0]), await body(refs[1])
            diff, truncated = unified_diff(before, after, limit=MAX_DIFF_CHARS)
            return {
                "page_id": found.id,
                "from_version": refs[0],
                "to_version": refs[1],
                "changed": before.strip() != after.strip(),
                "notice": NOTICE,
                "diff": wrap(diff, source=f"page {found.id}"),
                "diff_truncated": truncated,
            }

        async def kind(ref: str) -> str:
            if ref == CURRENT:
                return CURRENT
            try:
                wanted = uuid.UUID(ref)
            except ValueError:
                raise ToolError(
                    f"{ref!r} is not 'current', a version id or a snapshot id."
                ) from None
            if await snapshots.load(member_id, wanted) is not None:
                return "snapshot"
            return "version"

        return await as_member(members, action)
