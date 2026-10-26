"""Write tools end to end against real Docmost, as a regular member."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from docmost_mcp_remote.docmost.version import Version, parse_version
from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, MEMBER

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def server(migrated_database: str, tokens: dict[str, str]) -> Iterator[RunningServer]:
    # One server and one sign-in for the whole module: Docmost allows about ten
    # sign-ins per minute.
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as running:
        yield running


@pytest.fixture(scope="module")
def token(server: RunningServer) -> str:
    return server.token(scopes=("write", "delete"), email=MEMBER[0], password=MEMBER[1])


def test_write_tools(server: RunningServer, token: str) -> None:
    unique = uuid.uuid4().hex[:10]
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


def test_copy_and_move_between_spaces(server: RunningServer, token: str) -> None:
    unique = uuid.uuid4().hex[:10]
    spaces = {space["slug"]: space["id"] for space in server.call(token, "list_spaces")["spaces"]}
    general, other = spaces["general"], spaces["other"]
    assert server.call(token, "get_space", {"space_id": other})["your_role"] == "writer"

    page = server.call(
        token,
        "create_page",
        {"space_id": general, "title": f"Copy me {unique}", "content": f"Body {unique}"},
    )
    server.call(
        token,
        "create_page",
        {"space_id": general, "title": f"Child {unique}", "parent_page_id": page["id"]},
    )
    copy = server.call(token, "duplicate_page", {"page": page["id"]})
    assert copy["title"] == f"Copy of Copy me {unique}"
    assert copy["copied_child_pages"] == 1
    assert f"Body {unique}" in server.call(token, "get_page", {"page": copy["id"]})["content"]

    elsewhere = server.call(token, "duplicate_page", {"page": page["id"], "target_space_id": other})
    assert elsewhere["space_id"] == other
    assert elsewhere["title"] == f"Copy me {unique}"

    moved = server.call(token, "move_page_to_space", {"page": copy["id"], "space_id": other})
    assert moved["space_id"] == other
    assert server.call(token, "get_page", {"page": copy["id"]})["space"]["id"] == other

    comment = server.call(token, "add_comment", {"page": page["id"], "text": "Draft"})
    edited = server.call(
        token, "update_comment", {"comment_id": comment["id"], "text": f"Final {unique}"}
    )
    assert "Draft" in edited["previous_text"]
    comments = server.call(token, "list_comments", {"page_id": page["id"]})["comments"]
    assert f"Final {unique}" in comments[0]["text"]


def test_section_edit(server: RunningServer, token: str) -> None:
    unique = uuid.uuid4().hex[:10]
    general = next(
        space["id"]
        for space in server.call(token, "list_spaces")["spaces"]
        if space["slug"] == "general"
    )
    body = (
        f"Intro {unique} with **bold** and [a link](https://example.com).\n\n"
        "## Table\n\n| Name | Value |\n| --- | --- |\n| a | 1 |\n\n"
        "## Steps\n\n- [ ] first\n- [x] second\n\n```python\nprint('# not a heading')\n```\n\n"
        "## End\n\nBye."
    )
    page = server.call(
        token, "create_page", {"space_id": general, "title": f"Sections {unique}", "content": body}
    )
    outline = server.call(token, "get_page_outline", {"page": page["id"]})["sections"]
    assert [item["level"] for item in outline] == [0, 2, 2, 2]
    steps = server.call(token, "get_section", {"page": page["id"], "index": 2})
    preview = server.call(
        token,
        "replace_section",
        {
            "page": page["id"],
            "index": 2,
            "section_hash": steps["section_hash"],
            "content": f"Done {unique}.",
            "dry_run": True,
        },
    )
    assert f"+Done {unique}." in preview["diff"]
    written = server.call(
        token,
        "replace_section",
        {
            "page": page["id"],
            "index": 2,
            "section_hash": steps["section_hash"],
            "content": f"Done {unique}.",
        },
    )
    assert written["changed"] is True
    # Since Docmost 0.97 its Markdown round trip keeps the rest of this page as
    # it was; older versions export the table header as an empty row, which
    # the server reports.
    reported = server.call(token, "whoami")["docmost_version"]
    old = reported is not None and parse_version(reported) < Version(0, 97, 0)
    assert ("warning" in written) is old
    content = server.call(token, "get_page", {"page": page["id"]})["content"]
    assert f"Done {unique}." in content
    assert "second" not in content
    assert "| Name" in content
    assert "Bye." in content
