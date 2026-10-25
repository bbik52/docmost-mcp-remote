"""Write tools end to end against real Docmost, as a regular member."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, MEMBER

pytestmark = pytest.mark.integration


@pytest.fixture
def server(engine: AsyncEngine, tokens: dict[str, str]) -> Iterator[RunningServer]:
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as running:
        yield running


def test_write_tools(server: RunningServer) -> None:
    unique = uuid.uuid4().hex[:10]
    token = server.token(scopes=("write", "delete"), email=MEMBER[0], password=MEMBER[1])
    spaces = server.call(token, "list_spaces")["spaces"]
    general = next(space["id"] for space in spaces if space["slug"] == "general")

    parent = server.call(
        token, "create_page", {"space_id": general, "title": f"Parent {unique}", "content": "One"}
    )
    page = server.call(
        token,
        "create_page",
        {
            "space_id": general,
            "title": f"Notes {unique}",
            "content": f"First line {unique}",
            "parent_page_id": parent["id"],
        },
    )

    appended = server.call(token, "update_page", {"page": page["id"], "content": "Second line"})
    assert appended["changed"] is True
    body = server.call(token, "get_page", {"page": page["id"]})["content"]
    assert body.index(f"First line {unique}") < body.index("Second line")

    replaced = server.call(
        token, "update_page", {"page": page["id"], "content": "Only", "operation": "replace"}
    )
    assert "First line" not in server.call(token, "get_page", {"page": page["id"]})["content"]
    server.call(token, "restore_snapshot", {"snapshot_id": replaced["snapshot_id"]})
    restored = server.call(token, "get_page", {"page": page["id"]})["content"]
    assert "Second line" in restored
    snapshots = server.call(token, "list_snapshots", {"page": page["id"]})["snapshots"]
    assert [item["reason"] for item in snapshots] == [
        "restore_snapshot",
        "update_page:replace",
        "update_page:append",
    ]

    renamed = server.call(token, "rename_page", {"page": page["id"], "title": f"Renamed {unique}"})
    assert renamed["title"] == f"Renamed {unique}"

    # Positions are computed by this server and validated by Docmost.
    sibling = server.call(
        token,
        "create_page",
        {"space_id": general, "title": f"Sibling {unique}", "parent_page_id": parent["id"]},
    )
    server.call(
        token, "move_page", {"page": sibling["id"], "parent_page_id": parent["id"], "first": True}
    )
    children = server.call(
        token, "list_pages", {"space_id": general, "parent_page_id": parent["id"]}
    )
    assert children["pages"][0]["id"] == sibling["id"]
    server.call(
        token,
        "move_page",
        {"page": sibling["id"], "parent_page_id": parent["id"], "after_page_id": page["id"]},
    )
    children = server.call(
        token, "list_pages", {"space_id": general, "parent_page_id": parent["id"]}
    )
    assert [item["id"] for item in children["pages"]] == [page["id"], sibling["id"]]
    moved = server.call(token, "move_page", {"page": sibling["id"]})
    assert moved["parent_page_id"] is None

    comment = server.call(token, "add_comment", {"page": page["id"], "text": f"Hi {unique}"})
    reply = server.call(
        token,
        "add_comment",
        {"page": page["id"], "text": "Reply", "reply_to_comment_id": comment["id"]},
    )
    assert reply["parent_comment_id"] == comment["id"]
    comments = server.call(token, "list_comments", {"page_id": page["id"]})["comments"]
    assert f"Hi {unique}" in comments[0]["text"]

    server.call(token, "trash_page", {"page": sibling["id"]})
    # Docmost still serves a trashed page by id; get_page says so.
    assert server.call(token, "get_page", {"page": sibling["id"]})["in_trash"] is True
    trash = server.call(token, "list_trash", {"space_id": general})["pages"]
    assert sibling["id"] in {item["id"] for item in trash}
    server.call(token, "restore_page", {"page": sibling["id"]})
    assert server.call(token, "get_page", {"page": sibling["id"]})["in_trash"] is False
