from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import zipfile
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.db.engine import create_engine
from docmost_mcp_remote.tools.files import single_page
from docmost_mcp_remote.web import downloads
from tests.conftest import DATABASE_TEST_URL
from tests.fakes import error, ok
from tests.harness import RunningServer
from tests.test_write_tools import FakeDocmost

NOTE = {
    "id": "a1",
    "fileName": "notes.txt",
    "fileSize": 5,
    "mimeType": "text/plain; charset=utf-8",
    "pageId": "p1",
    "spaceId": "s1",
    "creator": {"id": "u1", "name": "Anna"},
    "createdAt": "2026-10-26T10:00:00Z",
}
SECRET_FILE = {**NOTE, "id": "a2", "pageId": "p3", "spaceId": "s2"}


def _file(content: bytes, name: str, kind: str = "application/octet-stream") -> httpx.Response:
    return httpx.Response(
        200,
        content=content,
        headers={"content-type": kind, "content-disposition": f'attachment; filename="{name}"'},
    )


@pytest.fixture
def docmost() -> FakeDocmost:
    docmost = FakeDocmost()
    uploads: list[dict[str, Any]] = []

    def export(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("includeChildren") or body.get("includeAttachments"):
            return _file(b"PK\x03\x04zip", "Guide.zip", "application/zip")
        if body["format"] == "html":
            return _file(b"<h1>Guide</h1>", "Guide.html")
        return _file(b"# Guide\n\nIntro", "Guide.md")

    def info(request: httpx.Request) -> httpx.Response:
        wanted = json.loads(request.content)["attachmentId"]
        found = next((item for item in (NOTE, SECRET_FILE, *uploads) if item["id"] == wanted), None)
        return ok(found) if found else error(404, "File not found")

    def upload(request: httpx.Request) -> httpx.Response:
        text = request.content.decode("latin-1")
        name = text.split('filename="', 1)[1].split('"', 1)[0]
        kind = text.split("Content-Type: ", 2)[-1].split("\r\n", 1)[0]
        item = {**NOTE, "id": f"u{len(uploads)}", "fileName": name, "mimeType": kind}
        uploads.append(item)
        return ok(item)

    def space_info(request: httpx.Request) -> httpx.Response:
        space_id = json.loads(request.content)["spaceId"]
        role = "writer" if space_id == "s9" else "admin"
        return ok({"id": space_id, "slug": "general", "membership": {"role": role}})

    docmost.recorder.routes.update(
        {
            "/api/pages/export": export,
            "/api/spaces/export": _file(b"PK\x03\x04space", "General.zip", "application/zip"),
            "/api/files/info": info,
            "/api/files/upload": upload,
            "/api/files/a1/notes.txt": _file(b"hello", "notes.txt", "text/plain"),
            "/api/pages/attachments": ok({"items": [NOTE], "meta": {"hasNextPage": False}}),
            "/api/spaces/info": space_info,
        }
    )
    return docmost


@pytest.fixture
def server(engine: AsyncEngine, docmost: FakeDocmost) -> Iterator[RunningServer]:
    with RunningServer(docmost.recorder.client(), allowed_spaces="general") as running:
        yield running


@pytest.fixture
def token(server: RunningServer) -> str:
    return server.token(scopes=("write",))


def _get(server: RunningServer, url: str) -> httpx.Response:
    return httpx.get(url.replace(server.public_url, server.url))


def test_export_single_page_inline(server: RunningServer, token: str) -> None:
    data = server.call(token, "export_page", {"page": "p1"})
    assert data["file_name"] == "Guide.md"
    assert "# Guide" in data["content"]
    assert "download_url" not in data
    html = server.call(token, "export_page", {"page": "p1", "format": "html"})
    assert "<h1>Guide</h1>" in html["content"]


def test_export_zip_by_link(server: RunningServer, token: str, docmost: FakeDocmost) -> None:
    data = server.call(token, "export_page", {"page": "p1", "include_children": True})
    assert "content" not in data
    response = _get(server, data["download_url"])
    assert response.status_code == 200
    assert response.content == b"PK\x03\x04zip"
    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''Guide.zip"
    assert response.headers["content-security-policy"] == "sandbox"
    assert docmost.requests("pages/export")[-1] == {
        "pageId": "p1",
        "format": "markdown",
        "includeChildren": True,
    }

    space = server.call(token, "export_space", {"space_id": "s1"})
    assert _get(server, space["download_url"]).content == b"PK\x03\x04space"


def test_space_export_needs_space_admin(engine: AsyncEngine, docmost: FakeDocmost) -> None:
    with (
        RunningServer(docmost.recorder.client()) as running,
        pytest.raises(ToolError, match="only admins"),
    ):
        running.call(running.token(), "export_space", {"space_id": "s9"})


def test_download_links_are_checked(
    server: RunningServer, token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = server.call(token, "export_space", {"space_id": "s1"})["download_url"]
    assert _get(server, url[:-2]).status_code == 404
    assert _get(server, f"{server.url}/downloads/not-a-link").status_code == 404
    assert _get(server, url).status_code == 200
    monkeypatch.setattr(downloads, "LINK_SECONDS", -1)
    expired = server.call(token, "export_space", {"space_id": "s1"})["download_url"]
    assert _get(server, expired).status_code == 404


def test_attachments(server: RunningServer, token: str) -> None:
    listed = server.call(token, "list_attachments", {"page": "p1"})
    assert listed["attachments"][0]["file_name"] == "notes.txt"
    found = server.call(token, "get_attachment", {"attachment_id": "a1"})
    assert "hello" in found["content"]
    assert _get(server, found["download_url"]).content == b"hello"
    with pytest.raises(ToolError, match="Space not found"):
        server.call(token, "get_attachment", {"attachment_id": "a2"})
    with pytest.raises(ToolError, match="Space not found"):
        server.call(token, "export_space", {"space_id": "s2"})


def test_upload_adds_the_file_to_the_page(
    server: RunningServer, token: str, docmost: FakeDocmost
) -> None:
    content = base64.b64encode(b"\x89PNG data").decode()
    added = server.call(
        token,
        "upload_attachment",
        {"page": "p1", "file_name": "chart.png", "content_base64": content},
    )
    assert added["added_to_page"] is True
    assert added["mime_type"] == "image/png"
    last = docmost.pages["p1"]["document"]["content"][-1]
    assert last["type"] == "image"
    assert last["attrs"]["src"] == "/api/files/u0/chart.png"

    kept = server.call(
        token,
        "upload_attachment",
        {"page": "p1", "file_name": "a.txt", "content_base64": "aGk=", "add_to_page": False},
    )
    assert kept["added_to_page"] is False

    with pytest.raises(ToolError, match="not valid base64"):
        server.call(
            token, "upload_attachment", {"page": "p1", "file_name": "x", "content_base64": "%%"}
        )


def test_upload_needs_write(server: RunningServer) -> None:
    tools = server.tools(server.token())
    assert "upload_attachment" not in tools
    assert "export_page" in tools


def test_access_log_hides_download_links() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s "%s %s"',
        ("1.2.3.4", "GET", "/downloads/abc"),
        None,
    )
    downloads.RedactDownloadLinks().filter(record)
    assert record.getMessage() == '1.2.3.4 "GET /downloads/[redacted]"'


def _zip(**files: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name.replace("_", "."), content)
    return buffer.getvalue()


def test_single_page_from_an_old_docmost_zip() -> None:
    assert single_page(b"# Plain", "Guide.md") == (b"# Plain", "Guide.md")
    old = _zip(Guide_md=b"# Guide", metadata_json=b"{}")
    assert single_page(old, "Guide.zip") == (b"# Guide", "Guide.md")
    assert single_page(_zip(Guide_md=b"a", Child_md=b"b"), "Guide.zip") is None


def test_links_end_with_their_grant(server: RunningServer, token: str) -> None:
    download = server.call(token, "export_space", {"space_id": "s1"})["download_url"]
    upload = server.call(token, "create_upload_link", {"page": "p1"})["upload_url"]
    upload = upload.replace(server.public_url, server.url)
    assert _get(server, download).status_code == 200
    assert httpx.get(upload).status_code == 200

    async def revoke() -> None:
        engine = create_engine(DATABASE_TEST_URL)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("UPDATE grants SET revoked_at = now()"))
        finally:
            await engine.dispose()

    asyncio.run(revoke())
    assert _get(server, download).status_code == 404
    assert httpx.get(upload).status_code == 404
    assert httpx.post(f"{upload}/done").status_code == 404
