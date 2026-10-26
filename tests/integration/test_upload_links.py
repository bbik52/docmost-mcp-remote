"""Upload links against real Docmost."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator

import httpx
import pytest

from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, MEMBER

pytestmark = pytest.mark.integration

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


@pytest.fixture(scope="module")
def server(migrated_database: str, tokens: dict[str, str]) -> Iterator[RunningServer]:
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as running:
        yield running


def test_upload_link(server: RunningServer) -> None:
    token = server.token(scopes=("write",), email=MEMBER[0], password=MEMBER[1])
    spaces = server.call(token, "list_spaces")["spaces"]
    general = next(space["id"] for space in spaces if space["slug"] == "general")
    page = server.call(
        token,
        "create_page",
        {
            "space_id": general,
            "title": f"Uploads {uuid.uuid4().hex[:8]}",
            "content": "## Screens\n\nBelow.\n\n## After\n\nEnd.",
        },
    )
    link = server.call(
        token, "create_upload_link", {"page": page["id"], "after_heading": "Screens"}
    )
    url = link["upload_url"].replace(server.public_url, server.url)
    files = [
        ("file", ("first.png", PNG, "image/png")),
        ("file", ("notes.txt", b"hi", "text/plain")),
    ]
    assert httpx.post(f"{url}/files", files=files, timeout=60).status_code == 200
    done = httpx.post(f"{url}/done", timeout=120)
    assert done.status_code == 200, done.text
    assert [item["file_name"] for item in done.json()["files"]] == ["first.png", "notes.txt"]

    result = server.call(token, "get_page", {"page": page["id"], "format": "json"})
    body = json.loads(result["content"].split("\n", 1)[1].rsplit("\n", 1)[0])
    kinds = [node["type"] for node in body["content"]]
    assert kinds[:4] == ["heading", "paragraph", "image", "attachment"]
    assert kinds[4] == "heading"
    status = server.call(token, "get_upload_status", {"upload_id": link["upload_id"]})
    assert status["state"] == "done"
