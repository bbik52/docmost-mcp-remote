"""Exports, attachments and uploads.

A single page is returned in the tool result. Zips (a page with its children
or files, a whole space) and attachments are offered as a short-lived link to
this server, which streams them from Docmost as the member: they are too
large and too binary for a tool result. Files go the other way through an
upload link, or, costing many tokens, as base64.
"""

from __future__ import annotations

import base64
import binascii
import io
import uuid
import zipfile
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import require_scopes
from pydantic import Field

from docmost_mcp_remote.auth import current_grant_id, current_member_id
from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.db.snapshot_store import SnapshotStore
from docmost_mcp_remote.docmost import DocmostBackend, DocmostResponseTooLargeError
from docmost_mcp_remote.docmost.models import Attachment, ExportFormat, Page
from docmost_mcp_remote.docmost.placement import Placement, file_node, insertion_index, place_files
from docmost_mcp_remote.docmost.version import Version
from docmost_mcp_remote.members import MemberService
from docmost_mcp_remote.tools.common import as_member, page_link, require_version
from docmost_mcp_remote.tools.read import Cursor, Limit, page_ref
from docmost_mcp_remote.tools.spaces import SpacePolicy
from docmost_mcp_remote.tools.untrusted import NOTICE, wrap
from docmost_mcp_remote.tools.write import write_document
from docmost_mcp_remote.web.downloads import LINK_SECONDS, DownloadLinks
from docmost_mcp_remote.web.uploads import UploadLinks, guess_type, safe_file_name

_READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
_WRITE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
#: First release that lists the attachments of a page.
ATTACHMENTS_SINCE = Version(0, 96, 0)
#: Largest file accepted by upload_attachment, after base64 decoding.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
#: Largest text attachment returned in the tool result.
MAX_INLINE_ATTACHMENT_BYTES = 256 * 1024
_TEXT_TYPES = ("application/json", "application/xml", "application/yaml", "application/x-yaml")
_LINK_NOTE = (
    f"Open download_url in a browser within {LINK_SECONDS // 60} minutes; anyone with the "
    "link can download the file until then, so do not share it."
)

PageRef = Annotated[str, Field(description="Page id, slug id or Docmost page URL.")]
AfterHeading = Annotated[
    str | None,
    Field(
        max_length=200,
        description="Put the files at the end of the section under this heading (its text).",
    ),
]
AfterText = Annotated[
    str | None,
    Field(
        max_length=200,
        description="Put the files right after the paragraph or block containing this text.",
    ),
]
Format = Annotated[ExportFormat, Field(description="markdown or html.")]


def _attachment(item: Attachment) -> dict[str, Any]:
    return {
        "id": item.id,
        "file_name": item.file_name,
        "size": item.file_size,
        "mime_type": item.mime_type,
        "page_id": item.page_id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "created_by": item.creator.name if item.creator else None,
    }


def _is_text(mime_type: str | None) -> bool:
    kind = (mime_type or "").split(";", 1)[0].strip().lower()
    return kind.startswith("text/") or kind in _TEXT_TYPES


def single_page(data: bytes, file_name: str | None) -> tuple[bytes, str | None] | None:
    """The page file of an export; None when the export holds more than one page.

    Docmost 0.70 answers even a single page with a zip that also holds a
    metadata file; later releases send the page file itself.
    """
    if not zipfile.is_zipfile(io.BytesIO(data)):
        return data, file_name
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        pages = [
            info
            for info in archive.infolist()
            if not info.is_dir() and info.filename.lower().endswith((".md", ".html"))
        ]
        if len(pages) != 1:
            return None
        return archive.read(pages[0]), pages[0].filename.rsplit("/", 1)[-1]


def register(
    mcp: FastMCP,
    settings: Settings,
    members: MemberService,
    snapshots: SnapshotStore,
    links: DownloadLinks,
    uploads: UploadLinks,
) -> None:
    policy = SpacePolicy(settings.allowed_spaces)
    docmost_base = str(settings.docmost_url).rstrip("/")

    async def load_page(backend: DocmostBackend, ref: str) -> Page:
        page = await backend.get_page(page_ref(ref))
        await policy.check(backend, page.space_id)
        return page

    @mcp.tool(
        name="export_page",
        description=(
            "Export a page as Docmost does, as Markdown or HTML. A single page is returned in "
            "the result; with its child pages or its files, or when it is too long, the result "
            f"is a download link to a zip that works for {LINK_SECONDS // 60} minutes. To "
            "read a page, use get_page; export when the person wants a file."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def export_page(
        page: PageRef,
        format: Format = "markdown",
        include_children: Annotated[bool, Field(description="Include child pages (zip).")] = False,
        include_attachments: Annotated[
            bool, Field(description="Include the files of the pages (zip).")
        ] = False,
    ) -> dict[str, Any]:
        member_id = current_member_id()
        grant_id = current_grant_id()

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            args = {
                "page_id": found.id,
                "format": format,
                "include_children": include_children,
                "include_attachments": include_attachments,
            }
            base = {"page_id": found.id, "title": found.title or "(untitled)", "format": format}
            if not include_children and not include_attachments:
                exported = await backend.export_page(found.id, format)
                try:
                    data = await exported.read(settings.max_page_chars * 4)
                except DocmostResponseTooLargeError:
                    data = None
                page_file = single_page(data, exported.file_name) if data is not None else None
                text = page_file[0].decode("utf-8", errors="replace") if page_file else None
                if page_file and text is not None and len(text) <= settings.max_page_chars:
                    return {
                        **base,
                        "file_name": page_file[1],
                        "notice": NOTICE,
                        "content": wrap(text, source=f"page {found.id} export"),
                    }
            return {
                **base,
                **links.create(member_id, grant_id, "page_export", args),
                "note": _LINK_NOTE,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="export_space",
        description=(
            "Export a whole space as a zip of Markdown or HTML files, optionally with its "
            "files. Needs admin rights in the space. The result is a download link that "
            f"works for {LINK_SECONDS // 60} minutes; Docmost builds the zip when the link "
            "is opened."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def export_space(
        space_id: Annotated[str, Field(description="Space id from list_spaces.")],
        format: Format = "markdown",
        include_attachments: Annotated[
            bool, Field(description="Include the files of the pages.")
        ] = False,
    ) -> dict[str, Any]:
        member_id = current_member_id()
        grant_id = current_grant_id()

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            await policy.check(backend, space_id)
            space = await backend.get_space(space_id)
            if space.member_role not in (None, "admin"):
                raise ToolError("Docmost lets only admins of a space export it.")
            args = {
                "space_id": space_id,
                "format": format,
                "include_attachments": include_attachments,
            }
            return {
                "space_id": space_id,
                "format": format,
                **links.create(member_id, grant_id, "space_export", args),
                "note": _LINK_NOTE,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="list_attachments",
        description="List the files uploaded to a page (Docmost 0.96 or newer).",
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def list_attachments(
        page: PageRef, cursor: Cursor = None, limit: Limit = 50
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            await require_version(backend, ATTACHMENTS_SINCE)
            found = await load_page(backend, page)
            result = await backend.page_attachments(found.id, cursor=cursor, limit=limit)
            return {
                "page_id": found.id,
                "notice": NOTICE,
                "attachments": [_attachment(item) for item in result.items],
                "next_cursor": result.next_cursor if result.has_next_page else None,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="get_attachment",
        description=(
            "Details of a file uploaded to a page, with a download link that works for "
            f"{LINK_SECONDS // 60} minutes. A small text file (up to "
            f"{MAX_INLINE_ATTACHMENT_BYTES // 1024} KB) is also returned in the result."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def get_attachment(
        attachment_id: Annotated[
            str, Field(description="Attachment id, from list_attachments or a page body.")
        ],
    ) -> dict[str, Any]:
        member_id = current_member_id()
        grant_id = current_grant_id()

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            item = await backend.attachment_info(attachment_id)
            if item.space_id:
                await policy.check(backend, item.space_id)
            elif item.page_id:
                await load_page(backend, item.page_id)
            else:
                raise ToolError("This file does not belong to a page.")
            result: dict[str, Any] = {
                **_attachment(item),
                **links.create(
                    member_id,
                    grant_id,
                    "attachment",
                    {"attachment_id": item.id, "file_name": item.file_name},
                ),
                "note": _LINK_NOTE,
            }
            size = item.file_size or 0
            if _is_text(item.mime_type) and size <= MAX_INLINE_ATTACHMENT_BYTES:
                download = await backend.download_attachment(item.id, item.file_name)
                try:
                    data = await download.read(MAX_INLINE_ATTACHMENT_BYTES)
                except DocmostResponseTooLargeError:
                    return result
                result["notice"] = NOTICE
                result["content"] = wrap(
                    data.decode("utf-8", errors="replace"), source=f"attachment {item.id}"
                )
            return result

        return await as_member(members, action)

    def placement_of(after_heading: str | None, after_text: str | None) -> Placement:
        if after_heading and after_text:
            raise ToolError("Give after_heading or after_text, not both.")
        return Placement(after_heading=after_heading or None, after_text=after_text or None)

    async def check_place(backend: DocmostBackend, page: Page, placement: Placement) -> None:
        if not placement.as_dict():
            return
        document = await backend.get_page_json(page.id)
        body = [node for node in document.get("content") or [] if isinstance(node, dict)]
        if insertion_index(body, placement) is None:
            what = "heading" if placement.after_heading else "text"
            raise ToolError(
                f"The page has no such {what}; check it with get_page_outline or get_page."
            )

    @mcp.tool(
        name="create_upload_link",
        description=(
            "Make a link for adding files to a page, and the best way to upload: it costs no "
            "tokens. Give the link to the person: they open it in a browser, drop in one or "
            "more files, put them in order and press Done, and the files appear in the page. "
            "If you can run commands with network access, send files you have yourself with "
            "the curl command in the result instead of upload_attachment. The link works for "
            f"{settings.upload_retention_minutes} minutes and takes files of up to "
            f"{settings.upload_max_mb} MB in total; files not added by then are deleted. "
            "Anyone with the link can add files to the page until then. Check the outcome "
            "with get_upload_status."
        ),
        annotations=_WRITE,
        auth=require_scopes("write"),
    )
    async def create_upload_link(
        page: PageRef, after_heading: AfterHeading = None, after_text: AfterText = None
    ) -> dict[str, Any]:
        member_id = current_member_id()
        grant_id = current_grant_id()
        placement = placement_of(after_heading, after_text)

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            await check_place(backend, found, placement)
            created = await uploads.create(
                member_id, grant_id, found, page_link(docmost_base, found), placement
            )
            return {
                "page_id": found.id,
                "title": found.title or "(untitled)",
                **created,
                "note": (
                    "Send upload_url to the person and tell them the files appear in the page "
                    "when they press Done. Do not share the link with anyone else."
                ),
            }

        return await as_member(members, action)

    @mcp.tool(
        name="get_upload_status",
        description=(
            "What happened to an upload link: the files sent to it so far and, once Done was "
            "pressed, whether they were added to the page."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def get_upload_status(
        upload_id: Annotated[str, Field(description="upload_id from create_upload_link.")],
    ) -> dict[str, Any]:
        member_id = current_member_id()
        try:
            link_id = uuid.UUID(upload_id)
        except ValueError:
            raise ToolError("Unknown upload_id.") from None
        found = await uploads.status(member_id, link_id)
        if found is None:
            raise ToolError("Unknown upload_id, or the link has expired.")
        return found

    @mcp.tool(
        name="upload_attachment",
        description=(
            "Upload a file to a page, given as base64, up to "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB. Base64 costs about a million tokens "
            "per megabyte, so prefer create_upload_link: tell the person that a link is much "
            "cheaper, and use this only for small files or when they choose it. By default "
            "the file is also added to the page, at the end or where after_heading or "
            "after_text say: images are shown, other files appear as a download block. "
            "Adding it saves a snapshot of the body first."
        ),
        annotations=_WRITE,
        auth=require_scopes("write"),
    )
    async def upload_attachment(
        page: PageRef,
        file_name: Annotated[
            str, Field(min_length=1, max_length=255, description="File name with extension.")
        ],
        content_base64: Annotated[
            str,
            Field(max_length=(MAX_UPLOAD_BYTES * 4) // 3 + 4, description="The file, base64."),
        ],
        mime_type: Annotated[
            str | None,
            Field(
                description="Type of the file; only used when the file name has no known "
                "extension. Pages and scripts (HTML, JavaScript, XML) are stored as downloads."
            ),
        ] = None,
        add_to_page: Annotated[
            bool, Field(description="Also show the file in the page body; false only attaches it.")
        ] = True,
        after_heading: AfterHeading = None,
        after_text: AfterText = None,
    ) -> dict[str, Any]:
        member_id = current_member_id()
        placement = placement_of(after_heading, after_text)
        name = safe_file_name(file_name)
        if not name:
            raise ToolError("Give a file name.")
        try:
            content = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError):
            raise ToolError("content_base64 is not valid base64.") from None
        if not content:
            raise ToolError("The file is empty.")
        if len(content) > MAX_UPLOAD_BYTES:
            raise ToolError(f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
        kind = guess_type(name, mime_type)

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await load_page(backend, page)
            if add_to_page:
                await check_place(backend, found, placement)
            item = await backend.upload_attachment(found.id, name, content, kind)
            result: dict[str, Any] = {**_attachment(item), "added_to_page": False}
            if not add_to_page:
                return result
            document = await backend.get_page_json(found.id)
            updated, _ = place_files(document, [file_node(item)], placement)
            try:
                snapshot_id, _ = await write_document(
                    backend, snapshots, members, member_id, found, updated, "upload_attachment"
                )
            except ToolError as exc:
                result["warning"] = f"The file was uploaded but not added to the page: {exc}"
                return result
            return {**result, "added_to_page": True, "snapshot_id": str(snapshot_id)}

        return await as_member(members, action)
