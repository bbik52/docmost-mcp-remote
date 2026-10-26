"""Tools that change Docmost (scopes ``write`` and ``delete``).

Every body write saves a snapshot of the current body first and reads the
page back afterwards: Docmost answers a body update with success even when
its collaboration service dropped it, so only the read-back proves it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import mcp_types as mt
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import require_scopes
from pydantic import Field

from docmost_mcp_remote.auth import current_member_id
from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.db.snapshot_store import SnapshotStore
from docmost_mcp_remote.docmost import DocmostBackend
from docmost_mcp_remote.docmost.documents import check_document, markdown_losses, outline
from docmost_mcp_remote.docmost.models import BodyOperation, Page, PageSummary, WorkspaceMember
from docmost_mcp_remote.docmost.positions import PositionError, position_between
from docmost_mcp_remote.docmost.prosemirror import doc_to_markdown, mention_node
from docmost_mcp_remote.members import MemberService
from docmost_mcp_remote.sections import (
    apply_operation,
    find_section,
    outside_kept,
    replace_section,
    unified_diff,
)
from docmost_mcp_remote.tools.common import as_member, formatting_hint, page_link
from docmost_mcp_remote.tools.confirm import confirm, named
from docmost_mcp_remote.tools.read import Cursor, Limit, page_ref
from docmost_mcp_remote.tools.spaces import SpacePolicy
from docmost_mcp_remote.tools.untrusted import NOTICE, wrap

logger = logging.getLogger(__name__)

#: Waits between read-backs after a body write, in seconds.
READ_BACK_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.5)
MAX_CONTENT_CHARS = 500_000
#: Largest ProseMirror JSON document accepted for a write, in characters.
MAX_JSON_CHARS = 2_000_000
MAX_DIFF_CHARS = 20_000
_MAX_SIBLING_PAGES = 10
#: Pages of workspace members read to find someone by id.
_MEMBER_PAGES = 10
MAX_MENTIONS = 10
#: Seconds after someone else saved a page during which it counts as being edited.
#: Docmost saves an open editor about every ten seconds while people type.
BUSY_SECONDS = 60

_WRITE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
_OVERWRITE = {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False}
_READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}

PageRef = Annotated[str, Field(description="Page id, slug id or Docmost page URL.")]
Markdown = Annotated[str, Field(max_length=MAX_CONTENT_CHARS, description="Markdown text.")]
Title = Annotated[str, Field(min_length=1, max_length=500, description="Page title.")]
DryRun = Annotated[bool, Field(description="Only show the change as a diff; write nothing.")]
DropFormatting = Annotated[
    bool,
    Field(
        description=(
            "Write even though the page has formatting Markdown cannot hold, which is then "
            "removed. Prefer replace_page_json for such pages."
        )
    ),
]

_NO_COLLAB = (
    "This happens when Docmost runs without the Redis of its collaboration service "
    "(COLLAB_DISABLE_REDIS); ask the Docmost admin."
)
NOT_SAVED = (
    f"Docmost accepted the change but the page body did not change. {_NO_COLLAB} "
    "Snapshot {snapshot} holds the body as it was."
)


async def read_back(backend: DocmostBackend, page_id: str, before: str) -> Page | None:
    """The page once its body differs from ``before``; None if it never does."""
    for delay in READ_BACK_DELAYS:
        await asyncio.sleep(delay)
        page = await backend.get_page(page_id)
        if page.content != before:
            return page
    return None


async def check_not_busy(members: MemberService, member_id: uuid.UUID, page: Page) -> None:
    """Refuse to rewrite a page that someone else saved in the last minute.

    A whole-body write replaces the document in the editor too, so what that
    person types meanwhile would be lost. Appending and prepending merge.
    """
    if page.updated_at is None or page.last_updated_by is None:
        return
    saved = page.updated_at
    if saved.tzinfo is None:
        saved = saved.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - saved).total_seconds()
    # Far in the future means the clocks disagree, and then the age says nothing.
    if not -BUSY_SECONDS < age < BUSY_SECONDS:
        return
    if page.last_updated_by.id == await members.docmost_user_id(member_id):
        return
    who = page.last_updated_by.name or "Someone"
    raise ToolError(
        f"Nothing was written: {who} saved this page {max(int(age), 0)} seconds ago and may "
        "be editing it right now, and rewriting the body would take away what they type. "
        f"Try again in a minute, or add text with update_page operation 'append' or "
        "'prepend', which keeps their changes."
    )


async def write_document(
    backend: DocmostBackend,
    snapshots: SnapshotStore,
    members: MemberService,
    member_id: uuid.UUID,
    page: Page,
    document: dict[str, Any],
    reason: str,
) -> tuple[uuid.UUID, bool]:
    """Replace a page body with a ProseMirror document: the snapshot id and whether it changed.

    The document is checked first, because Docmost silently drops what it cannot
    read. What Docmost stored is compared with what was sent, and the previous
    body is put back when they differ.
    """
    problems = check_document(document)
    if problems:
        raise ToolError("The document was not written: " + " ".join(problems))
    if len(json.dumps(document)) > MAX_JSON_CHARS:
        raise ToolError(f"The document is larger than {MAX_JSON_CHARS} characters of JSON.")
    await check_not_busy(members, member_id, page)
    current = await backend.get_page_json(page.id)
    snapshot_id = await snapshots.save(
        member_id=member_id,
        page_id=page.id,
        space_id=page.space_id,
        title=page.title,
        content=json.dumps(current, ensure_ascii=False),
        reason=reason,
        format="json",
    )
    if document == current:
        return snapshot_id, False
    await backend.replace_page_json(page.id, document)
    stored: dict[str, Any] | None = None
    for delay in READ_BACK_DELAYS:
        await asyncio.sleep(delay)
        found = await backend.get_page_json(page.id)
        if found != current:
            stored = found
            break
    wanted = outline(document)
    if stored is None:
        # Docmost fills in default attributes, so a document that only repeats
        # the current one in another spelling stores nothing new.
        if wanted == outline(current):
            return snapshot_id, False
        logger.warning("JSON write to page %s was not applied by Docmost", page.id)
        raise ToolError(NOT_SAVED.format(snapshot=snapshot_id))
    got = outline(stored)
    if got != wanted:
        logger.warning("Docmost changed the JSON written to page %s; putting it back", page.id)
        await backend.replace_page_json(page.id, current)
        index = next(
            (i for i, (a, b) in enumerate(zip(wanted, got, strict=False)) if a != b),
            min(len(wanted), len(got)),
        )
        seen = got[index][0] if index < len(got) else "the end of the page"
        sent = wanted[index][0] if index < len(wanted) else "the end of the page"
        raise ToolError(
            f"Docmost did not store the document as sent (node {index}: sent {sent}, stored "
            f"{seen}), so the previous body was put back. This Docmost release may not know "
            f"one of the node types. Snapshot {snapshot_id} holds the previous body."
        )
    logger.info("Member %s wrote page %s as JSON (%s)", member_id, page.id, reason)
    return snapshot_id, True


async def _all_children(
    backend: DocmostBackend, space_id: str, parent_page_id: str | None
) -> list[PageSummary]:
    pages: list[PageSummary] = []
    cursor: str | None = None
    for _ in range(_MAX_SIBLING_PAGES):
        result = await backend.list_pages(
            space_id, parent_page_id=parent_page_id, cursor=cursor, limit=100
        )
        pages.extend(result.items)
        if not result.has_next_page or not result.next_cursor:
            return pages
        cursor = result.next_cursor
    raise ToolError("Too many pages at this level to place a page; move it in Docmost.")


async def find_person(backend: DocmostBackend, ref: str) -> WorkspaceMember:
    """One workspace member by email, exact name or user id."""
    wanted = ref.strip().lower()
    found = await backend.workspace_members(query=ref.strip(), limit=100)
    for key in ("email", "name"):
        matches = [item for item in found.items if (getattr(item, key) or "").lower() == wanted]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ToolError(f"Several people are named {ref!r}; give their email.")
    cursor: str | None = None
    for _ in range(_MEMBER_PAGES):
        page = await backend.workspace_members(cursor=cursor, limit=100)
        match = next((item for item in page.items if item.id == ref.strip()), None)
        if match is not None:
            return match
        if not page.has_next_page or not page.next_cursor:
            break
        cursor = page.next_cursor
    raise ToolError(f"No workspace member matches {ref!r}; give their email.")


def new_position(siblings: list[PageSummary], *, after_page_id: str | None, first: bool) -> str:
    """A position at the start, at the end, or right after one sibling."""
    keys = sorted(page.position for page in siblings if page.position)
    if after_page_id is not None:
        after = next((page for page in siblings if page.id == after_page_id), None)
        if after is None or not after.position:
            raise ToolError("after_page_id is not a page at the target level.")
        later = [key for key in keys if key > after.position]
        low, high = after.position, (later[0] if later else None)
    elif first:
        low, high = None, (keys[0] if keys else None)
    else:
        low, high = (keys[-1] if keys else None), None
    try:
        return position_between(low, high)
    except PositionError as exc:
        raise ToolError(f"Cannot place the page there: {exc}.") from None


def register(
    mcp: FastMCP, settings: Settings, members: MemberService, snapshots: SnapshotStore
) -> None:
    policy = SpacePolicy(settings.allowed_spaces)
    docmost_base = str(settings.docmost_url).rstrip("/")

    def result(page: Page, **extra: Any) -> dict[str, Any]:
        return {
            "id": page.id,
            "slug_id": page.slug_id,
            "title": page.title or "(untitled)",
            "url": page_link(docmost_base, page),
            **extra,
        }

    async def load_page(backend: DocmostBackend, ref: str) -> Page:
        page = await backend.get_page(page_ref(ref))
        await policy.check(backend, page.space_id)
        return page

    async def write_body(
        backend: DocmostBackend,
        member_id: uuid.UUID,
        page: Page,
        content: str,
        operation: BodyOperation,
        reason: str,
    ) -> dict[str, Any]:
        if operation == "replace":
            await check_not_busy(members, member_id, page)
        snapshot_id = await snapshots.save(
            member_id=member_id,
            page_id=page.id,
            space_id=page.space_id,
            title=page.title,
            content=page.content,
            reason=reason,
        )
        if operation == "replace" and content.strip() == page.content.strip():
            return result(page, snapshot_id=str(snapshot_id), changed=False)
        await backend.update_page_body(page.id, content, operation)
        updated = await read_back(backend, page.id, page.content)
        if updated is None:
            logger.warning("Body write to page %s was not applied by Docmost", page.id)
            raise ToolError(NOT_SAVED.format(snapshot=snapshot_id))
        logger.info("Member %s wrote page %s (%s)", member_id, page.id, reason)
        return result(
            updated,
            snapshot_id=str(snapshot_id),
            changed=True,
            content_chars=len(updated.content),
        )

    def preview(page: Page, proposed: str, losses: list[str] | None = None) -> dict[str, Any]:
        diff, truncated = unified_diff(page.content, proposed, limit=MAX_DIFF_CHARS)
        extra: dict[str, Any] = {}
        if losses:
            extra = {"formatting_removed": losses, "hint": formatting_hint(losses)}
        return result(
            page,
            dry_run=True,
            changed=proposed.strip() != page.content.strip(),
            notice=NOTICE,
            diff=wrap(diff, source=f"page {page.id}"),
            diff_truncated=truncated,
            **extra,
        )

    async def guard_formatting(
        backend: DocmostBackend, page: Page, *, dry_run: bool, drop_formatting: bool
    ) -> list[str]:
        """Formatting a Markdown replace would remove; refuses a real write unless allowed."""
        losses = markdown_losses(await backend.get_page_json(page.id))
        if losses and not dry_run and not drop_formatting:
            raise ToolError(
                f"Nothing was written: replacing this page with Markdown would remove its "
                f"{', '.join(losses)}. Edit it with get_page format='json' and "
                "replace_page_json, add text with operation 'append' or 'prepend', or pass "
                "drop_formatting=true to remove the formatting."
            )
        return losses

    @mcp.tool(
        name="create_page",
        description=(
            "Create a page in a space, optionally under a parent page and with a Markdown body. "
            "Returns the new page's id and link."
        ),
        annotations=_WRITE,
        auth=require_scopes("write"),
    )
    async def create_page(
        space_id: Annotated[str, Field(description="Space id from list_spaces.")],
        title: Title,
        content: Markdown = "",
        parent_page_id: Annotated[
            str | None, Field(description="Create the page under this page.")
        ] = None,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            await policy.check(backend, space_id)
            parent = page_ref(parent_page_id) if parent_page_id else None
            if parent is not None:
                parent_page = await backend.get_page(parent)
                if parent_page.space_id != space_id:
                    raise ToolError("parent_page_id is in another space.")
                parent = parent_page.id
            created = await backend.create_page(
                space_id, title, markdown=content, parent_page_id=parent
            )
            page = await backend.get_page(created.id)
            if content.strip() and not page.content.strip():
                raise ToolError(
                    f"Page {page.id} was created but Docmost did not save its body. {_NO_COLLAB}"
                )
            return result(page, content_chars=len(page.content))

        return await as_member(members, action)

    @mcp.tool(
        name="update_page",
        description=(
            "Change a page body with Markdown. Prefer operation 'append' or 'prepend', which "
            "keep the existing text, comments and formatting. 'replace' rewrites the whole "
            "body; read the page first and send the complete new body. It is refused on pages "
            "with formatting Markdown cannot hold (get_page lists it in markdown_loses); use "
            "replace_page_json there. 'replace' is also refused while someone else is editing "
            "the page. The previous body is saved as a snapshot that "
            "restore_snapshot can bring back. With dry_run=true nothing is written and the "
            "result shows the change as a diff. To change one part of a long page, prefer "
            "replace_section."
        ),
        annotations=_OVERWRITE,
        auth=require_scopes("write"),
    )
    async def update_page(
        page: PageRef,
        content: Markdown,
        operation: Annotated[
            Literal["append", "prepend", "replace"],
            Field(description="append: add at the end; prepend: at the start; replace: all."),
        ] = "append",
        dry_run: DryRun = False,
        drop_formatting: DropFormatting = False,
    ) -> dict[str, Any]:
        member_id = current_member_id()

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            losses: list[str] = []
            if operation == "replace":
                losses = await guard_formatting(
                    backend, found, dry_run=dry_run, drop_formatting=drop_formatting
                )
            if dry_run:
                return preview(found, apply_operation(found.content, content, operation), losses)
            return await write_body(
                backend, member_id, found, content, operation, f"update_page:{operation}"
            )

        return await as_member(members, action)

    @mcp.tool(
        name="replace_page_json",
        description=(
            "Replace a whole page body with a ProseMirror JSON document, as get_page with "
            "format='json' returns it. Unlike Markdown this keeps everything Docmost can show: "
            "colors, merged table cells, columns, diagrams, mentions, comment highlights. "
            "Read the page as JSON first, change it and send the complete document. It is "
            "checked against Docmost's editor schema before anything is written, refused while "
            "someone else is editing the page, and the previous body is saved as a snapshot. "
            "With dry_run=true nothing is written; the result lists any problems and shows "
            "the change as a Markdown diff."
        ),
        annotations=_OVERWRITE,
        auth=require_scopes("write"),
    )
    async def replace_page_json(
        page: PageRef,
        document: Annotated[
            dict[str, Any],
            Field(description="The ProseMirror document: {'type': 'doc', 'content': [...]}."),
        ],
        dry_run: DryRun = False,
    ) -> dict[str, Any]:
        member_id = current_member_id()

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            if dry_run:
                problems = check_document(document)
                current = doc_to_markdown(await backend.get_page_json(found.id))
                proposed = "" if problems else doc_to_markdown(document)
                diff, truncated = unified_diff(current, proposed, limit=MAX_DIFF_CHARS)
                return result(
                    found,
                    dry_run=True,
                    problems=problems,
                    changed=not problems and proposed.strip() != current.strip(),
                    notice=NOTICE,
                    diff=wrap(diff, source=f"page {found.id}") if not problems else None,
                    diff_truncated=truncated,
                )
            snapshot_id, changed = await write_document(
                backend, snapshots, members, member_id, found, document, "replace_page_json"
            )
            return result(found, snapshot_id=str(snapshot_id), changed=changed)

        return await as_member(members, action)

    @mcp.tool(
        name="replace_section",
        description=(
            "Replace one section of a page, found with get_page_outline and read with "
            "get_section. Pass the section_hash from get_section: if the section changed "
            "since, nothing is written. By default the heading is kept and content replaces "
            "what is under it, subsections included; with keep_heading=false content replaces "
            "the heading too, and an empty content removes the section. The whole body is "
            "saved as a snapshot first. The whole body is rewritten from Markdown, so this is "
            "refused on pages with formatting Markdown cannot hold, as update_page replace is."
        ),
        annotations=_OVERWRITE,
        auth=require_scopes("write"),
    )
    async def replace_section_tool(
        page: PageRef,
        index: Annotated[int, Field(ge=0, description="Section index from get_page_outline.")],
        section_hash: Annotated[str, Field(description="section_hash from get_section.")],
        content: Annotated[
            str, Field(max_length=MAX_CONTENT_CHARS, description="New Markdown for the section.")
        ],
        keep_heading: Annotated[bool, Field(description="Keep the section's heading line.")] = True,
        dry_run: DryRun = False,
        drop_formatting: DropFormatting = False,
    ) -> dict[str, Any]:
        member_id = current_member_id()

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            section = find_section(found.content, index)
            if section is None or section.hash != section_hash:
                raise ToolError(
                    "The section changed since you read it, or the index is wrong. Call "
                    "get_page_outline and get_section again."
                )
            new_text = content.strip()
            if keep_heading and section.level:
                new_text = f"{section.heading_line}\n\n{new_text}".strip()
            proposed = replace_section(found.content, section, new_text)
            losses = await guard_formatting(
                backend, found, dry_run=dry_run, drop_formatting=drop_formatting
            )
            if dry_run:
                return preview(found, proposed, losses)
            if not proposed.strip():
                raise ToolError("This would leave the page empty; use update_page instead.")
            written = await write_body(
                backend, member_id, found, proposed, "replace", "replace_section"
            )
            if written.get("changed"):
                updated = await backend.get_page(found.id)
                if not outside_kept(updated.content, found.content, section):
                    written["warning"] = (
                        "Docmost also changed text outside the section while converting the "
                        "Markdown. Compare with the snapshot and restore it if needed."
                    )
            return written

        return await as_member(members, action)

    @mcp.tool(
        name="rename_page",
        description="Change the title of a page.",
        annotations=_WRITE,
        auth=require_scopes("write"),
    )
    async def rename_page(page: PageRef, title: Title) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            await backend.rename_page(found.id, title)
            renamed = await backend.get_page(found.id)
            if renamed.title != title:
                raise ToolError("Docmost did not save the new title.")
            return result(renamed, previous_title=found.title)

        return await as_member(members, action)

    @mcp.tool(
        name="move_page",
        description=(
            "Move a page to another place in the same space: under parent_page_id, or to the "
            "top level when it is empty. The page goes to the end of that level, to the start "
            "with first=true, or right after after_page_id. Child pages move with it."
        ),
        annotations=_WRITE,
        auth=require_scopes("write"),
    )
    async def move_page(
        page: PageRef,
        parent_page_id: Annotated[
            str | None, Field(description="New parent page; empty for the top level.")
        ] = None,
        after_page_id: Annotated[
            str | None, Field(description="Place right after this page at the new level.")
        ] = None,
        first: Annotated[bool, Field(description="Place at the start of the level.")] = False,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            parent = None
            if parent_page_id:
                parent_page = await backend.get_page(page_ref(parent_page_id))
                if parent_page.space_id != found.space_id:
                    raise ToolError("Pages can only be moved within their space.")
                if parent_page.id == found.id:
                    raise ToolError("A page cannot be its own parent.")
                parent = parent_page.id
            siblings = [
                sibling
                for sibling in await _all_children(backend, found.space_id, parent)
                if sibling.id != found.id
            ]
            after = page_ref(after_page_id) if after_page_id else None
            if after is not None:
                after = next(
                    (sibling.id for sibling in siblings if after in (sibling.id, sibling.slug_id)),
                    after,
                )
            position = new_position(siblings, after_page_id=after, first=first)
            await backend.move_page(found.id, parent_page_id=parent, position=position)
            moved = await backend.get_page(found.id)
            if moved.parent_page_id != parent:
                raise ToolError("Docmost did not move the page.")
            return result(moved, parent_page_id=parent)

        return await as_member(members, action)

    @mcp.tool(
        name="move_page_to_space",
        description=(
            "Move a page with its child pages to the top level of another space. Everyone in "
            "the target space gains access to them and members of the old space may lose it. "
            "Child pages you cannot access stay behind as top-level pages of the old space."
        ),
        annotations=_WRITE,
        auth=require_scopes("write"),
    )
    async def move_page_to_space(
        page: PageRef,
        space_id: Annotated[str, Field(description="Target space id from list_spaces.")],
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            if found.space_id == space_id:
                raise ToolError("The page is already in this space; use move_page instead.")
            await policy.check(backend, space_id)
            await backend.move_page_to_space(found.id, space_id)
            moved = await backend.get_page(found.id)
            if moved.space_id != space_id:
                raise ToolError("Docmost did not move the page.")
            logger.info("Moved page %s to space %s", found.id, space_id)
            return result(moved, previous_space_id=found.space_id, space_id=space_id)

        return await as_member(members, action)

    @mcp.tool(
        name="duplicate_page",
        description=(
            "Copy a page with its child pages, attachments and labels. Without target_space_id "
            "the copy lands next to the original and is titled 'Copy of ...'; with it, the "
            "copy goes to the top level of that space under the same title. Comments and "
            "history are not copied."
        ),
        annotations=_WRITE,
        auth=require_scopes("write"),
    )
    async def duplicate_page(
        page: PageRef,
        target_space_id: Annotated[
            str | None, Field(description="Copy into this space instead of the same one.")
        ] = None,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            target = target_space_id if target_space_id != found.space_id else None
            if target is not None:
                await policy.check(backend, target)
            copied = await backend.duplicate_page(found.id, space_id=target)
            created = await backend.get_page(copied.id)
            logger.info("Copied page %s to %s", found.id, created.id)
            return result(
                created,
                source_page_id=found.id,
                space_id=created.space_id,
                copied_child_pages=len(copied.child_page_ids),
            )

        return await as_member(members, action)

    @mcp.tool(
        name="add_comment",
        description=(
            "Add a comment to a page as plain text, or a reply to a comment with "
            "reply_to_comment_id. Comments are visible to everyone who can see the page. "
            "People in mention (emails, names or user ids) are @-mentioned at the start of "
            "the comment, and Docmost notifies them; mention someone only when they need to "
            "act on it."
        ),
        annotations=_WRITE,
        auth=require_scopes("write"),
    )
    async def add_comment(
        page: PageRef,
        text: Annotated[str, Field(min_length=1, max_length=10_000)],
        reply_to_comment_id: Annotated[
            str | None, Field(description="Id of the comment to reply to.")
        ] = None,
        mention: Annotated[
            list[str] | None,
            Field(max_length=MAX_MENTIONS, description="People to @-mention: email, name or id."),
        ] = None,
    ) -> dict[str, Any]:
        member_id = current_member_id()

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            people = [await find_person(backend, ref) for ref in dict.fromkeys(mention or [])]
            me = await members.docmost_user_id(member_id) if people else None
            comment = await backend.create_comment(
                found.id,
                text,
                parent_comment_id=reply_to_comment_id,
                mentions=[
                    mention_node(person.id, person.name or person.email or person.id, me)
                    for person in people
                ],
            )
            result: dict[str, Any] = {
                "id": comment.id,
                "page_id": found.id,
                "parent_comment_id": comment.parent_comment_id,
            }
            if people:
                result["mentioned"] = [{"id": person.id, "name": person.name} for person in people]
            return result

        return await as_member(members, action)

    @mcp.tool(
        name="update_comment",
        description=(
            "Replace the text of one of your own comments with plain text. Docmost only lets "
            "you edit comments you wrote. The previous text is returned."
        ),
        annotations=_OVERWRITE,
        auth=require_scopes("write"),
    )
    async def update_comment(
        comment_id: Annotated[str, Field(description="Comment id from list_comments.")],
        text: Annotated[str, Field(min_length=1, max_length=10_000)],
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            comment = await backend.get_comment(comment_id)
            space_id = comment.space_id or (await backend.get_page(comment.page_id)).space_id
            await policy.check(backend, space_id)
            updated = await backend.update_comment(comment.id, text)
            return {
                "id": updated.id,
                "page_id": comment.page_id,
                "notice": NOTICE,
                "previous_text": wrap(comment.text, source=f"comment {comment.id}"),
            }

        return await as_member(members, action)

    @mcp.tool(
        name="list_trash",
        description="List the pages in the Trash of a space, most recently deleted first.",
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def list_trash(
        space_id: Annotated[str, Field(description="Space id from list_spaces.")],
        cursor: Cursor = None,
        limit: Limit = 50,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            await policy.check(backend, space_id)
            found = await backend.list_trash(space_id, cursor=cursor, limit=limit)
            return {
                "pages": [
                    {
                        "id": item.id,
                        "slug_id": item.slug_id,
                        "title": item.title or "(untitled)",
                        "deleted_at": item.deleted_at.isoformat() if item.deleted_at else None,
                    }
                    for item in found.items
                ],
                "next_cursor": found.next_cursor if found.has_next_page else None,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="trash_page",
        description=(
            "Move a page and its child pages to the Trash of its space. It can be restored with "
            "restore_page. This server never deletes pages permanently. Clients that can ask "
            "the person first do so."
        ),
        annotations=_OVERWRITE,
        auth=require_scopes("delete"),
    )
    async def trash_page(page: PageRef) -> dict[str, Any] | mt.InputRequiredResult:
        async def action(backend: DocmostBackend) -> dict[str, Any] | mt.InputRequiredResult:
            found = await load_page(backend, page)
            asked = await confirm(
                f"Move the page {named(found.title)} and its child pages to the Trash?"
            )
            if isinstance(asked, mt.InputRequiredResult):
                return asked
            await backend.move_to_trash(found.id)
            logger.info("Moved page %s to Trash", found.id)
            return result(found, trashed=True)

        return await as_member(members, action)

    @mcp.tool(
        name="restore_page",
        description=(
            "Restore a page from the Trash, with its child pages. Use list_trash to find it."
        ),
        annotations=_WRITE,
        auth=require_scopes("delete"),
    )
    async def restore_page(
        page: Annotated[str, Field(description="Page id or slug id from list_trash.")],
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            ref = page_ref(page)
            await backend.restore_from_trash(ref)
            restored = await load_page(backend, ref)
            logger.info("Restored page %s from Trash", restored.id)
            return result(restored, restored=True)

        return await as_member(members, action)

    @mcp.tool(
        name="list_snapshots",
        description=(
            "List the snapshots of a page body that this server saved before your own changes "
            f"to it, newest first. Snapshots are kept {settings.snapshot_retention_days} days."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def list_snapshots(
        page: PageRef, limit: Annotated[int, Field(ge=1, le=100)] = 20
    ) -> dict[str, Any]:
        member_id = current_member_id()

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            items = await snapshots.list(member_id, found.id, limit)
            return {
                "page_id": found.id,
                "snapshots": [
                    {
                        "id": str(item.id),
                        "created_at": item.created_at.isoformat(),
                        "reason": item.reason,
                        "content_chars": item.content_chars,
                    }
                    for item in items
                ],
            }

        return await as_member(members, action)

    @mcp.tool(
        name="restore_snapshot",
        description=(
            "Put a page body back to a snapshot from list_snapshots. The current body is "
            "saved as a new snapshot first, so a restore can be undone the same way."
        ),
        annotations=_OVERWRITE,
        auth=require_scopes("write"),
    )
    async def restore_snapshot(
        snapshot_id: Annotated[str, Field(description="Snapshot id from list_snapshots.")],
    ) -> dict[str, Any]:
        member_id = current_member_id()
        try:
            wanted = uuid.UUID(snapshot_id)
        except ValueError:
            raise ToolError("Snapshot not found.") from None
        snapshot = await snapshots.load(member_id, wanted)
        if snapshot is None:
            raise ToolError("Snapshot not found.")

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, snapshot.info.page_id)
            if snapshot.format == "json":
                saved, changed = await write_document(
                    backend,
                    snapshots,
                    members,
                    member_id,
                    found,
                    json.loads(snapshot.content),
                    "restore_snapshot",
                )
                written = result(found, snapshot_id=str(saved), changed=changed)
            else:
                written = await write_body(
                    backend, member_id, found, snapshot.content, "replace", "restore_snapshot"
                )
            return {**written, "restored_snapshot_id": snapshot_id}

        return await as_member(members, action)
