"""ProseMirror JSON reads and writes against real Docmost."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastmcp.exceptions import ToolError

from docmost_mcp_remote.docmost.documents import outline
from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, MEMBER

pytestmark = pytest.mark.integration

RICH: dict[str, Any] = {
    "type": "doc",
    "content": [
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Plan"}]},
        {
            "type": "callout",
            "attrs": {"type": "warning"},
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Red",
                            "marks": [{"type": "textStyle", "attrs": {"color": "#ff0000"}}],
                        }
                    ],
                }
            ],
        },
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [
                        {
                            "type": "tableHeader",
                            "attrs": {"colspan": 2},
                            "content": [
                                {"type": "paragraph", "content": [{"type": "text", "text": "Both"}]}
                            ],
                        }
                    ],
                },
                {
                    "type": "tableRow",
                    "content": [
                        {
                            "type": "tableCell",
                            "content": [
                                {"type": "paragraph", "content": [{"type": "text", "text": "A"}]}
                            ],
                        },
                        {
                            "type": "tableCell",
                            "content": [
                                {"type": "paragraph", "content": [{"type": "text", "text": "B"}]}
                            ],
                        },
                    ],
                },
            ],
        },
    ],
}


@pytest.fixture(scope="module")
def server(migrated_database: str, tokens: dict[str, str]) -> Iterator[RunningServer]:
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as running:
        yield running


def _document(result: dict[str, Any]) -> Any:
    return json.loads(result["content"].split("\n", 1)[1].rsplit("\n", 1)[0])


def test_json_round_trip(server: RunningServer) -> None:
    token = server.token(scopes=("write",), email=MEMBER[0], password=MEMBER[1])
    spaces = server.call(token, "list_spaces")["spaces"]
    general = next(space["id"] for space in spaces if space["slug"] == "general")
    page = server.call(
        token,
        "create_page",
        {"space_id": general, "title": f"JSON {uuid.uuid4().hex[:8]}", "content": "Plain"},
    )["id"]

    preview = server.call(
        token, "replace_page_json", {"page": page, "document": RICH, "dry_run": True}
    )
    assert preview["problems"] == []
    written = server.call(token, "replace_page_json", {"page": page, "document": RICH})
    assert written["changed"] is True

    stored = _document(server.call(token, "get_page", {"page": page, "format": "json"}))
    assert outline(stored) == outline(RICH)
    header = stored["content"][2]["content"][0]["content"][0]
    assert header["attrs"]["colspan"] == 2
    red = stored["content"][1]["content"][0]["content"][0]
    assert red["marks"][0]["attrs"]["color"] == "#ff0000"

    markdown = server.call(token, "get_page", {"page": page})
    assert markdown["markdown_loses"] == ["merged table cells", "text colors"]
    with pytest.raises(ToolError, match="would remove"):
        server.call(token, "update_page", {"page": page, "content": "x", "operation": "replace"})

    restored = server.call(token, "restore_snapshot", {"snapshot_id": written["snapshot_id"]})
    assert restored["changed"] is True
    plain = server.call(token, "get_page", {"page": page})
    assert "Plain" in plain["content"]
    assert plain["markdown_loses"] == []


def test_restore_page_version(server: RunningServer) -> None:
    token = server.token(scopes=("write",), email=MEMBER[0], password=MEMBER[1])
    spaces = server.call(token, "list_spaces")["spaces"]
    general = next(space["id"] for space in spaces if space["slug"] == "general")
    page = server.call(
        token,
        "create_page",
        {"space_id": general, "title": f"Version {uuid.uuid4().hex[:8]}", "content": "Before"},
    )["id"]
    server.call(token, "replace_page_json", {"page": page, "document": RICH})
    # Docmost saves a version about a minute after the last edit of a new page.
    versions: list[dict[str, Any]] = []
    for _ in range(90):
        versions = server.call(token, "list_page_history", {"page": page})["versions"]
        if versions:
            break
        time.sleep(2)
    assert versions, "Docmost saved no page version"
    server.call(
        token,
        "update_page",
        {"page": page, "content": "After", "operation": "replace", "drop_formatting": True},
    )

    restored = server.call(token, "restore_page_version", {"version_id": versions[0]["id"]})
    assert restored["changed"] is True
    stored = _document(server.call(token, "get_page", {"page": page, "format": "json"}))
    assert outline(stored) == outline(RICH)
