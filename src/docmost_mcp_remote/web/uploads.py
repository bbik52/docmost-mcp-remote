"""Upload links: a page in the browser, or a plain POST, to add files to a Docmost page.

An assistant asks for a link to one page and a place in it. Whoever opens the
link can send files to it until it expires; they are kept here, encrypted,
and only go to Docmost, as the member who asked for the link, when "Done" is
pressed. Files that never get there are deleted with the link when it
expires. Sending files through a link costs the assistant no tokens, unlike
passing them to upload_attachment as base64.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import secrets
import uuid
from datetime import timedelta
from importlib.resources import files as package_files
from typing import Any

from fastmcp.exceptions import ToolError
from jinja2 import Environment, PackageLoader, select_autoescape
from starlette.datastructures import UploadFile as FormFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.db.snapshot_store import SnapshotStore
from docmost_mcp_remote.db.store import now
from docmost_mcp_remote.db.upload_store import (
    UploadFile,
    UploadLimitError,
    UploadLink,
    UploadStore,
)
from docmost_mcp_remote.docmost import DocmostBackend, DocmostError
from docmost_mcp_remote.docmost.models import Attachment, Page
from docmost_mcp_remote.docmost.placement import Placement, file_node, place_files
from docmost_mcp_remote.members import MemberService, SessionExpiredError
from docmost_mcp_remote.tools.spaces import SpacePolicy
from docmost_mcp_remote.tools.write import write_document

logger = logging.getLogger(__name__)

UPLOAD_PATH = "/uploads/{token}"
#: Most files one link takes.
MAX_FILES = 50
#: Largest body of a Done request, which only carries the order of the files.
MAX_DONE_BYTES = 64 * 1024
_SCRIPT = package_files("docmost_mcp_remote.web").joinpath("upload.js").read_text()
_CSP = (
    "default-src 'none'; style-src 'self'; script-src 'self'; img-src blob:; "
    "connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"
)
_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
_GONE = "This upload link is not valid or has expired."


def safe_file_name(name: str) -> str:
    """A file name without path separators; empty when nothing usable is left."""
    cleaned = name.replace("/", "_").replace("\\", "_").replace("\x00", "").strip()[:255]
    return "" if cleaned in ("", ".", "..") else cleaned


def guess_type(name: str, given: str | None) -> str:
    kind = (given or "").split(";", 1)[0].strip().lower()
    if kind and kind != "application/octet-stream":
        return kind
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _file(item: UploadFile) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "file_name": item.file_name,
        "mime_type": item.mime_type,
        "size": item.size,
        "in_docmost": item.attachment_id is not None,
    }


def _json(data: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers=_HEADERS)


def _error(message: str, status: int) -> JSONResponse:
    return _json({"error": message}, status)


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


class UploadLinks:
    def __init__(
        self,
        settings: Settings,
        members: MemberService,
        store: UploadStore,
        snapshots: SnapshotStore,
    ) -> None:
        self._base = settings.public_base
        self._members = members
        self._store = store
        self._snapshots = snapshots
        self.lifetime = timedelta(minutes=settings.upload_retention_minutes)
        self.max_bytes = settings.upload_max_mb * 1024 * 1024
        self._policy = SpacePolicy(settings.allowed_spaces)
        self._templates = Environment(
            loader=PackageLoader("docmost_mcp_remote.web", "templates"),
            autoescape=select_autoescape(default=True),
        )

    async def create(
        self,
        member_id: uuid.UUID,
        grant_id: uuid.UUID,
        page: Page,
        page_url: str | None,
        placement: Placement,
    ) -> dict[str, Any]:
        """A new link to ``page``, as tool result fields; it ends if ``grant_id`` is revoked."""
        token = secrets.token_urlsafe(32)
        link = await self._store.create(
            member_id=member_id,
            grant_id=grant_id,
            token=token,
            page_id=page.id,
            details={
                "title": page.title or "(untitled)",
                "url": page_url,
                "space_id": page.space_id,
                "placement": placement.as_dict(),
            },
            lifetime=self.lifetime,
        )
        url = f"{self._base}/uploads/{token}"
        return {
            "upload_id": str(link.id),
            "upload_url": url,
            "expires_at": link.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "placement": placement.describe(),
            "curl": f"curl -F file=@picture.png {url}/files && curl -X POST {url}/done",
        }

    async def status(self, member_id: uuid.UUID, link_id: uuid.UUID) -> dict[str, Any] | None:
        link = await self._store.by_id(member_id, link_id)
        if link is None:
            return None
        found = await self._store.files(link.id)
        return {
            "upload_id": str(link.id),
            "page_id": link.page_id,
            "state": link.state,
            "expires_at": link.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            **{key: value for key, value in (link.outcome or {}).items() if key != "files"},
            "files": [{**_file(item), "attachment_id": item.attachment_id} for item in found],
        }

    async def cleanup(self) -> int:
        return await self._store.cleanup()

    def routes(self) -> list[Route]:
        return [
            Route("/assets/upload.js", self.script, methods=["GET"]),
            Route(UPLOAD_PATH, self.page, methods=["GET"]),
            Route(UPLOAD_PATH + "/files", self.receive, methods=["POST"]),
            Route(UPLOAD_PATH + "/files/{file_id}", self.remove, methods=["DELETE"]),
            Route(UPLOAD_PATH + "/done", self.done, methods=["POST"]),
        ]

    async def script(self, _: Request) -> Response:
        return Response(
            _SCRIPT,
            media_type="text/javascript",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    async def _link(self, request: Request) -> UploadLink | None:
        return await self._store.by_token(request.path_params["token"])

    async def page(self, request: Request) -> Response:
        link = await self._link(request)
        if link is None:
            return self._render("message.html", 404, title="Link expired", message=_GONE)
        found = await self._store.files(link.id)
        placement = Placement(**link.details.get("placement", {}))
        return self._render(
            "upload.html",
            200,
            link=link,
            title=link.details.get("title"),
            page_url=link.details.get("url") or (link.outcome or {}).get("page_url"),
            placement=placement.describe(),
            minutes=max(1, int((link.expires_at - now()).total_seconds() // 60)),
            expires_at=link.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            expires_time=link.expires_at.strftime("%H:%M UTC"),
            max_mb=self.max_bytes // (1024 * 1024),
            max_files=MAX_FILES,
            files_json=json.dumps([_file(item) for item in found]),
        )

    def _render(self, name: str, status: int, **context: Any) -> HTMLResponse:
        html = self._templates.get_template(name).render(**context)
        return HTMLResponse(html, status_code=status, headers=_HEADERS)

    async def receive(self, request: Request) -> Response:
        link = await self._link(request)
        if link is None:
            return _error(_GONE, 404)
        if link.state != "open":
            return _error("The files of this link were already added to the page.", 409)
        # The declared length bounds what is read: the HTTP server never reads past
        # it, while a chunked body could go on without end.
        declared = request.headers.get("content-length", "")
        if not declared.isdigit() or "transfer-encoding" in request.headers:
            return _error("Send the files with a Content-Length header.", 411)
        if int(declared) > self.max_bytes + 1024 * 1024:
            return _error(f"The files may be {self.max_bytes // (1024 * 1024)} MB in total.", 413)
        try:
            form = await request.form(max_files=MAX_FILES, max_fields=10)
        except (HTTPException, MultiPartException):
            return _error("Send the files as multipart/form-data.", 400)
        saved: list[dict[str, Any]] = []
        try:
            sent = [value for _, value in form.multi_items() if isinstance(value, FormFile)]
            if not sent:
                return _error("No files were sent.", 400)
            for item in sent:
                name = safe_file_name(item.filename or "")
                if not name:
                    return _json({"files": saved, "error": "A file has no name."}, 400)
                content = await item.read(self.max_bytes + 1)
                if not content:
                    return _json({"files": saved, "error": f"{name} is empty."}, 400)
                try:
                    stored = await self._store.add_file(
                        link,
                        file_name=name,
                        mime_type=guess_type(name, item.content_type),
                        content=content,
                        max_bytes=self.max_bytes,
                        max_files=MAX_FILES,
                    )
                except UploadLimitError as exc:
                    return _json({"files": saved, "error": str(exc)}, 413)
                saved.append(_file(stored))
        finally:
            await form.close()
        return _json({"files": saved})

    async def remove(self, request: Request) -> Response:
        link = await self._link(request)
        if link is None:
            return _error(_GONE, 404)
        file_id = _uuid(request.path_params["file_id"])
        if file_id is None or not await self._store.remove_file(link.id, file_id):
            return _error("This file cannot be removed.", 404)
        return _json({"removed": str(file_id)})

    async def done(self, request: Request) -> Response:
        link = await self._link(request)
        if link is None:
            return _error(_GONE, 404)
        order: list[uuid.UUID] = []
        body = await _read_limited(request, MAX_DONE_BYTES)
        if body is None:
            return _error("The request is too large.", 413)
        if body:
            try:
                wanted = json.loads(body).get("order") or []
            except (ValueError, AttributeError):
                return _error('Send {"order": [file ids]} or nothing.', 400)
            order = [found for found in map(_uuid, wanted) if found]
        if not await self._store.start_adding(link.id):
            if link.state == "done":
                return _json(link.outcome or {})
            return _error("The files are being added already.", 409)
        try:
            outcome = await self._add(link, order)
        except _Failed as exc:
            await self._store.finish(link.id, "open", {"error": str(exc)})
            return _error(str(exc), exc.status)
        except Exception:
            await self._store.finish(link.id, "open", {"error": "adding the files failed"})
            raise
        await self._store.finish(link.id, "done", outcome)
        logger.info(
            "Member %s added %d files through an upload link", link.member_id, len(outcome["files"])
        )
        return _json(outcome)

    async def _add(self, link: UploadLink, order: list[uuid.UUID]) -> dict[str, Any]:
        placement = Placement(**link.details.get("placement", {}))

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            found = await self._store.files(link.id)
            if order:
                # The browser names the files to add, in its order; others are left out.
                rank = {file_id: index for index, file_id in enumerate(order)}
                found = sorted(
                    (item for item in found if item.id in rank), key=lambda item: rank[item.id]
                )
            if not found:
                raise _Failed("Add files first.", 400)
            page = await backend.get_page(link.page_id)
            await self._policy.check(backend, page.space_id)
            attachments: list[Attachment] = []
            for item in found:
                attachment_id = item.attachment_id
                if attachment_id is None:
                    content = await self._store.content(link.id, item.id)
                    if content is None:
                        continue
                    uploaded = await backend.upload_attachment(
                        page.id, item.file_name, content, item.mime_type
                    )
                    attachment_id = uploaded.id
                    await self._store.uploaded(link.id, item.id, attachment_id)
                attachments.append(
                    Attachment.model_validate(
                        {
                            "id": attachment_id,
                            "fileName": item.file_name,
                            "fileSize": item.size,
                            "mimeType": item.mime_type,
                        }
                    )
                )
            document = await backend.get_page_json(page.id)
            updated, place_found = place_files(
                document, [file_node(item) for item in attachments], placement
            )
            snapshot_id, _ = await write_document(
                backend,
                self._snapshots,
                self._members,
                link.member_id,
                page,
                updated,
                "upload_link",
            )
            outcome: dict[str, Any] = {
                "added_to_page": True,
                "page_url": link.details.get("url"),
                "placement": placement.describe() if place_found else "at the end of the page",
                "snapshot_id": str(snapshot_id),
                "files": [
                    {"file_name": item.file_name, "attachment_id": item.id} for item in attachments
                ],
            }
            if not place_found:
                outcome["warning"] = (
                    f"The page no longer has the place asked for ({placement.describe()}), "
                    "so the files went to the end of the page."
                )
            return outcome

        try:
            return await self._members.run(link.member_id, action)
        except SessionExpiredError as exc:
            raise _Failed(f"{exc} Then press Done again.", 401) from None
        except ToolError as exc:
            raise _Failed(f"The files are not in the page yet: {exc}", 409) from None
        except DocmostError as exc:
            logger.warning("Upload link %s: Docmost refused the files: %s", link.id, exc)
            raise _Failed(f"Docmost refused the files: {exc}", 502) from None


async def _read_limited(request: Request, limit: int) -> bytes | None:
    """The request body, or None when it is longer than ``limit`` bytes."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        return None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            return None
    return bytes(body)


class _Failed(Exception):
    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status
