"""Short-lived download links for files too large to return in a tool result.

A link carries, encrypted and authenticated with the server key, the member,
what to download and when the link expires. Opening it streams the file from
Docmost with that member's session; nothing is stored on this server. Anyone
holding a link can use it until it expires, so links live ten minutes.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
import uuid
from typing import Any, Literal
from urllib.parse import quote

from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route

from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.crypto import Cipher, DecryptionError
from docmost_mcp_remote.docmost import (
    DocmostBackend,
    DocmostError,
    DocmostForbiddenError,
    DocmostNotFoundError,
)
from docmost_mcp_remote.docmost.downloads import Download
from docmost_mcp_remote.members import MemberService, SessionExpiredError

logger = logging.getLogger(__name__)

DOWNLOAD_PATH = "/downloads/{token}"
LINK_SECONDS = 600
_CONTEXT = "download-link"
_HEADERS = {
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    "content-security-policy": "sandbox",
    "referrer-policy": "no-referrer",
}

Kind = Literal["page_export", "space_export", "attachment"]
_LINK_IN_PATH = re.compile(r"/downloads/[^/?\s\"]+")


class RedactDownloadLinks(logging.Filter):
    """Keeps download links out of the HTTP access log: a link is a credential."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                _LINK_IN_PATH.sub("/downloads/[redacted]", arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


class DownloadLinks:
    def __init__(self, settings: Settings, members: MemberService, cipher: Cipher) -> None:
        self._base = settings.public_base
        self._members = members
        self._cipher = cipher

    def create(self, member_id: uuid.UUID, kind: Kind, args: dict[str, Any]) -> dict[str, Any]:
        """A link for ``member_id`` and when it expires, as tool result fields."""
        expires = int(time.time()) + LINK_SECONDS
        payload = json.dumps({"m": str(member_id), "k": kind, "a": args, "x": expires})
        blob = self._cipher.encrypt(payload, context=_CONTEXT)
        token = base64.urlsafe_b64encode(blob).decode().rstrip("=")
        return {
            "download_url": f"{self._base}/downloads/{token}",
            "download_expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires)),
        }

    def _read(self, token: str) -> tuple[uuid.UUID, Kind, dict[str, Any]] | None:
        try:
            blob = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            data = json.loads(self._cipher.decrypt(blob, context=_CONTEXT))
        except (ValueError, DecryptionError):
            return None
        if not isinstance(data, dict) or int(data.get("x", 0)) < time.time():
            return None
        return uuid.UUID(data["m"]), data["k"], dict(data["a"])

    def routes(self) -> list[Route]:
        return [Route(DOWNLOAD_PATH, self.download, methods=["GET"])]

    async def download(self, request: Request) -> Response:
        link = self._read(request.path_params["token"])
        if link is None:
            return _text("This download link is not valid or has expired.", 404)
        member_id, kind, args = link

        async def open_file(backend: DocmostBackend) -> Download:
            if kind == "page_export":
                return await backend.export_page(
                    args["page_id"],
                    args["format"],
                    include_children=args["include_children"],
                    include_attachments=args["include_attachments"],
                )
            if kind == "space_export":
                return await backend.export_space(
                    args["space_id"],
                    args["format"],
                    include_attachments=args["include_attachments"],
                )
            return await backend.download_attachment(args["attachment_id"], args["file_name"])

        try:
            found = await self._members.run(member_id, open_file)
        except SessionExpiredError:
            return _text("Your session on this server has ended; sign in again.", 401)
        except (DocmostNotFoundError, DocmostForbiddenError):
            return _text("Docmost no longer finds this, or you no longer have access.", 404)
        except DocmostError as exc:
            logger.warning("Download for member %s failed: %s", member_id, exc)
            return _text("Docmost could not provide the file; try again later.", 502)
        name = found.file_name or args.get("file_name") or "download"
        headers = {
            **_HEADERS,
            "content-disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}",
        }
        logger.info("Member %s downloaded a %s", member_id, kind.replace("_", " "))
        return StreamingResponse(
            found.chunks,
            media_type=found.content_type,
            headers=headers,
            background=BackgroundTask(found.close),
        )


def _text(message: str, status: int) -> PlainTextResponse:
    return PlainTextResponse(message, status_code=status, headers=_HEADERS)
