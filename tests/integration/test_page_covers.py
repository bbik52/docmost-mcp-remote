from __future__ import annotations

import base64
import os
import struct
import zlib

import pytest

from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, OWNER

pytestmark = pytest.mark.integration


def _png() -> str:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    image = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    image += chunk(b"IDAT", zlib.compress(b"\x00\x20\x40\x80")) + chunk(b"IEND", b"")
    return base64.b64encode(image).decode()


def test_preset_attachment_and_cover_removal_preserve_body(
    migrated_database: str, tokens: dict[str, str]
) -> None:
    if os.environ.get("DOCMOST_VERSION") not in {"0.98.0", "latest"}:
        pytest.skip("Page covers need Docmost 0.98+")
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as server:
        token = server.token(scopes=("write",), email=OWNER[0], password=OWNER[1])
        space = next(
            s for s in server.call(token, "list_spaces")["spaces"] if s["slug"] == "general"
        )
        page = server.call(
            token,
            "create_page",
            {"space_id": space["id"], "title": "Cover test", "content": "Keep this body"},
        )
        result = server.call(
            token, "set_page_cover", {"page": page["id"], "preset": "color-blue", "position": 35}
        )
        assert result["cover"] == {"photo": "preset:color-blue", "position": 35}
        upload = server.call(
            token,
            "upload_attachment",
            {
                "page": page["id"],
                "file_name": "cover.png",
                "content_base64": _png(),
                "mime_type": "image/png",
                "add_to_page": False,
            },
        )
        baseline = server.call(token, "get_page", {"page": page["id"], "format": "json"})["content"]
        result = server.call(
            token,
            "set_page_cover",
            {"page": page["id"], "attachment_id": upload["id"]},
        )
        assert result["cover"]["photo"].startswith("/api/files/")
        assert (
            server.call(token, "set_page_cover", {"page": page["id"], "remove": True})["cover"][
                "photo"
            ]
            is None
        )
        assert (
            server.call(token, "get_page", {"page": page["id"], "format": "json"})["content"]
            == baseline
        )
