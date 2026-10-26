"""Exports and attachments against real Docmost."""

from __future__ import annotations

import base64
import io
import uuid
import zipfile
from collections.abc import Iterator

import httpx
import pytest
from fastmcp.exceptions import ToolError

from docmost_mcp_remote.docmost.version import Version
from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, MEMBER, OWNER, reported_version

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def server(migrated_database: str, tokens: dict[str, str]) -> Iterator[RunningServer]:
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as running:
        yield running


def _download(server: RunningServer, url: str) -> httpx.Response:
    # Links carry the public address; the test server listens on its own.
    return httpx.get(url.replace(server.public_url, server.url), timeout=60)


def test_export_and_attachments(server: RunningServer) -> None:
    token = server.token(scopes=("write",), email=MEMBER[0], password=MEMBER[1])
    unique = uuid.uuid4().hex[:8]
    spaces = server.call(token, "list_spaces")["spaces"]
    general = next(space["id"] for space in spaces if space["slug"] == "general")
    page = server.call(
        token,
        "create_page",
        {"space_id": general, "title": f"Export {unique}", "content": "Some **bold** text"},
    )["id"]
    server.call(
        token, "create_page", {"space_id": general, "title": "Child", "parent_page_id": page}
    )

    single = server.call(token, "export_page", {"page": page})
    assert "Some **bold** text" in single["content"]
    assert single["file_name"].endswith(".md")
    html = server.call(token, "export_page", {"page": page, "format": "html"})
    assert "<strong>bold</strong>" in html["content"]

    tree = server.call(token, "export_page", {"page": page, "include_children": True})
    response = _download(server, tree["download_url"])
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    assert any(name.endswith("Child.md") for name in names)
    assert _download(server, tree["download_url"] + "x").status_code == 404

    uploaded = server.call(
        token,
        "upload_attachment",
        {
            "page": page,
            "file_name": "notes.txt",
            "content_base64": base64.b64encode(b"hello attachment").decode(),
        },
    )
    assert uploaded["added_to_page"] is True
    assert uploaded["mime_type"].startswith("text/plain")
    body = server.call(token, "get_page", {"page": page, "format": "json"})["content"]
    assert uploaded["id"] in body

    info = server.call(token, "get_attachment", {"attachment_id": uploaded["id"]})
    assert "hello attachment" in info["content"]
    assert _download(server, info["download_url"]).content == b"hello attachment"

    image = server.call(
        token,
        "upload_attachment",
        {
            "page": page,
            "file_name": "dot.png",
            "content_base64": base64.b64encode(_PNG).decode(),
        },
    )
    assert image["added_to_page"] is True

    version = reported_version(server, token)
    if version is None or version >= Version(0, 96, 0):
        listed = server.call(token, "list_attachments", {"page": page})
        assert {item["id"] for item in listed["attachments"]} >= {uploaded["id"], image["id"]}

    with pytest.raises(ToolError, match="only admins"):
        server.call(token, "export_space", {"space_id": general})
    owner = server.token(scopes=("read",), email=OWNER[0], password=OWNER[1])
    space = server.call(owner, "export_space", {"space_id": general})
    got = _download(server, space["download_url"])
    assert got.content[:2] == b"PK", got.text


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
