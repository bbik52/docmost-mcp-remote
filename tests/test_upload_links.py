from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.crypto import Cipher
from docmost_mcp_remote.db.engine import create_engine
from docmost_mcp_remote.db.upload_store import UploadStore
from docmost_mcp_remote.docmost.placement import Placement, insertion_index, place_files
from docmost_mcp_remote.web import downloads
from tests.conftest import DATABASE_TEST_URL, SECRET
from tests.harness import RunningServer
from tests.test_file_tools import docmost  # noqa: F401 - the fixture
from tests.test_write_tools import FakeDocmost


def _heading(level: int, title: str) -> dict[str, Any]:
    return {
        "type": "heading",
        "attrs": {"level": level},
        "content": [{"type": "text", "text": title}],
    }


def _para(words: str = "") -> dict[str, Any]:
    if not words:
        return {"type": "paragraph"}
    return {"type": "paragraph", "content": [{"type": "text", "text": words}]}


BODY = [
    _heading(1, "Guide"),
    _para("Intro"),
    _heading(2, "Setup"),
    _para("Install it"),
    _heading(3, "Details"),
    _para("More"),
    _para(),
    _heading(2, "Usage"),
    _para("Run it"),
    _para(),
]


def test_insertion_index() -> None:
    assert insertion_index(BODY, Placement()) == 9
    assert insertion_index(BODY, Placement(after_heading="setup")) == 6
    assert insertion_index(BODY, Placement(after_heading="Details")) == 6
    assert insertion_index(BODY, Placement(after_heading="  usage ")) == 9
    assert insertion_index(BODY, Placement(after_text="install")) == 4
    assert insertion_index(BODY, Placement(after_heading="Missing")) is None
    assert insertion_index(BODY, Placement(after_text="nowhere")) is None
    assert insertion_index([], Placement()) == 0


def test_place_files_falls_back_to_the_end() -> None:
    image = {"type": "image", "attrs": {"src": "/x.png"}}
    placed, found = place_files({"type": "doc", "content": BODY}, [image], Placement("Gone"))
    assert not found
    assert placed["content"][9] == image
    assert placed["content"][-1] == _para()


@pytest.fixture
def server(engine: AsyncEngine, docmost: FakeDocmost) -> Iterator[RunningServer]:  # noqa: F811
    with RunningServer(docmost.recorder.client(), allowed_spaces="general") as running:
        yield running


@pytest.fixture
def token(server: RunningServer) -> str:
    return server.token(scopes=("write",))


def _local(server: RunningServer, url: str) -> str:
    return url.replace(server.public_url, server.url)


def _sql(statement: str) -> None:
    async def run() -> None:
        engine = create_engine(DATABASE_TEST_URL or "")
        try:
            async with engine.begin() as connection:
                await connection.execute(text(statement))
        finally:
            await engine.dispose()

    asyncio.run(run())


def _send(url: str, *files: tuple[str, bytes, str]) -> httpx.Response:
    return httpx.post(f"{url}/files", files=[("file", item) for item in files])


def test_upload_link_flow(server: RunningServer, token: str, docmost: FakeDocmost) -> None:  # noqa: F811
    steps = [_heading(1, "Guide"), _heading(2, "Steps"), _para("First"), _heading(2, "End")]
    docmost.pages["p1"]["document"] = {"type": "doc", "content": steps}
    link = server.call(token, "create_upload_link", {"page": "p1", "after_heading": "Steps"})
    assert link["placement"] == 'at the end of the section "Steps"'
    assert "curl -F file=@" in link["curl"]
    url = _local(server, link["upload_url"])

    page = httpx.get(url)
    assert page.status_code == 200
    assert "Add files to “Guide”" in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert "deleted from this server" in page.text

    sent = _send(url, ("one.png", b"\x89PNG one", "image/png"), ("notes.txt", b"hi", ""))
    assert sent.status_code == 200
    one, notes = sent.json()["files"]
    assert notes["mime_type"] == "text/plain"
    two = _send(url, ("two.png", b"\x89PNG two", "image/png")).json()["files"][0]
    assert httpx.delete(f"{url}/files/{notes['id']}").status_code == 200

    status = server.call(token, "get_upload_status", {"upload_id": link["upload_id"]})
    assert status["state"] == "open"
    assert [item["file_name"] for item in status["files"]] == ["one.png", "two.png"]
    assert not any(item.url.path == "/api/files/upload" for item in docmost.recorder.requests)

    done = httpx.post(f"{url}/done", json={"order": [two["id"], one["id"]]})
    assert done.status_code == 200, done.text
    assert [item["file_name"] for item in done.json()["files"]] == ["two.png", "one.png"]
    content = docmost.pages["p1"]["document"]["content"]
    assert [node["type"] for node in content] == [
        "heading",
        "heading",
        "paragraph",
        "image",
        "image",
        "heading",
    ]
    assert [node["attrs"]["alt"] for node in content[3:5]] == ["two.png", "one.png"]

    status = server.call(token, "get_upload_status", {"upload_id": link["upload_id"]})
    assert status["state"] == "done"
    assert status["added_to_page"] is True
    assert all(item["in_docmost"] for item in status["files"])
    assert httpx.post(f"{url}/done").json() == done.json()
    assert _send(url, ("late.png", b"x", "image/png")).status_code == 409
    assert "These files are in the page now" in httpx.get(url).text


def test_upload_link_checks(server: RunningServer, token: str, docmost: FakeDocmost) -> None:  # noqa: F811
    with pytest.raises(ToolError, match="no such heading"):
        server.call(token, "create_upload_link", {"page": "p1", "after_heading": "Nope"})
    with pytest.raises(ToolError, match="not both"):
        server.call(
            token, "create_upload_link", {"page": "p1", "after_heading": "a", "after_text": "b"}
        )
    with pytest.raises(ToolError, match="not found"):
        server.call(token, "create_upload_link", {"page": "p3"})
    with pytest.raises(ToolError, match="Unknown upload_id"):
        server.call(token, "get_upload_status", {"upload_id": "x"})

    url = _local(server, server.call(token, "create_upload_link", {"page": "p1"})["upload_url"])
    assert httpx.post(f"{url}/done").status_code == 400
    assert httpx.post(f"{url}/files", content=b"nothing").status_code == 400
    assert _send(url, ("empty.txt", b"", "text/plain")).status_code == 400
    assert httpx.get(url[:-3]).status_code == 404
    assert httpx.post(f"{url[:-3]}/files").status_code == 404


def test_upload_link_limits(engine: AsyncEngine, docmost: FakeDocmost) -> None:  # noqa: F811
    with RunningServer(docmost.recorder.client(), upload_max_mb=1) as running:
        token = running.token(scopes=("write",))
        url = _local(
            running, running.call(token, "create_upload_link", {"page": "p1"})["upload_url"]
        )
        assert _send(url, ("a.bin", b"x" * 600_000, "")).status_code == 200
        refused = _send(url, ("b.bin", b"x" * 600_000, ""))
        assert refused.status_code == 413
        assert "1 MB in total" in refused.json()["error"]

        def chunks() -> Iterator[bytes]:
            yield b"--x\r\n"

        chunked = httpx.post(
            f"{url}/files",
            content=chunks(),
            headers={"content-type": "multipart/form-data; boundary=x"},
        )
        assert chunked.status_code == 411
        assert httpx.post(f"{url}/done", content=b" " * 70_000).status_code == 413


def test_expired_links_are_deleted(
    server: RunningServer,
    token: str,
    docmost: FakeDocmost,  # noqa: F811
) -> None:
    link = server.call(token, "create_upload_link", {"page": "p1"})
    url = _local(server, link["upload_url"])
    assert _send(url, ("a.png", b"\x89PNG", "image/png")).status_code == 200
    _sql("UPDATE upload_links SET expires_at = now() - interval '1 minute'")
    assert httpx.get(url).status_code == 404
    assert _send(url, ("b.png", b"\x89PNG", "image/png")).status_code == 404
    with pytest.raises(ToolError, match="expired"):
        server.call(token, "get_upload_status", {"upload_id": link["upload_id"]})


async def test_cleanup_deletes_expired_links(engine: AsyncEngine) -> None:
    store = UploadStore(engine, Cipher(SECRET))
    async with engine.begin() as connection:
        member = await connection.execute(
            text(
                "INSERT INTO members (id, docmost_user_id, email) "
                "VALUES (gen_random_uuid(), 'u-clean', 'c@example.com') RETURNING id"
            )
        )
        member_id = member.scalar_one()
    kept = await store.create(
        member_id=member_id,
        token="kept",
        page_id="p1",
        details={},
        lifetime=timedelta(minutes=5),
    )
    gone = await store.create(
        member_id=member_id,
        token="gone",
        page_id="p1",
        details={},
        lifetime=timedelta(minutes=-1),
    )
    await store.add_file(
        kept, file_name="a", mime_type="text/plain", content=b"a", max_bytes=10, max_files=5
    )
    assert await store.cleanup() == 1
    assert await store.by_token("kept") is not None
    assert await store.by_id(member_id, gone.id) is None
    assert await store.content(kept.id, (await store.files(kept.id))[0].id) == b"a"


def test_access_log_hides_upload_links() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s "%s %s"',
        ("1.2.3.4", "POST", "/uploads/abc/files"),
        None,
    )
    downloads.RedactDownloadLinks().filter(record)
    assert record.getMessage() == '1.2.3.4 "POST /uploads/[redacted]/files"'


def test_upload_attachment_at_a_place(
    server: RunningServer,
    token: str,
    docmost: FakeDocmost,  # noqa: F811
) -> None:
    body = [_para("First"), _para("Second"), _para()]
    docmost.pages["p1"]["document"] = {"type": "doc", "content": body}
    args = {"page": "p1", "file_name": "a.png", "content_base64": "iVBORw==", "after_text": "first"}
    assert server.call(token, "upload_attachment", args)["added_to_page"] is True
    content = docmost.pages["p1"]["document"]["content"]
    assert [node["type"] for node in content] == ["paragraph", "image", "paragraph", "paragraph"]
    with pytest.raises(ToolError, match="no such text"):
        server.call(token, "upload_attachment", {**args, "after_text": "nowhere"})
    sent = [item for item in docmost.recorder.requests if item.url.path == "/api/files/upload"]
    assert len(sent) == 1
