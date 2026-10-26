from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.docmost.documents import check_document, outline
from docmost_mcp_remote.tools import write
from tests.harness import RunningServer
from tests.test_write_tools import FakeDocmost

V1 = str(uuid.UUID(int=1))
V9 = str(uuid.UUID(int=9))
GLOW = {"type": "glow"}


def _doc(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {"type": "doc", "content": list(blocks)}


def _para(text: str, **attrs: Any) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "paragraph", "content": [{"type": "text", "text": text}]}
    if attrs:
        node["attrs"] = attrs
    return node


COLORED = _doc(
    {
        "type": "heading",
        "attrs": {"level": 2},
        "content": [{"type": "text", "text": "Plan"}],
    },
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
                        "marks": [{"type": "textStyle", "attrs": {"color": "#f00"}}],
                    }
                ],
            }
        ],
    },
)


@pytest.fixture
def docmost() -> FakeDocmost:
    docmost = FakeDocmost()
    docmost.add_version(V1, "p1", "Old text")
    return docmost


@pytest.fixture
def server(
    engine: AsyncEngine, docmost: FakeDocmost, monkeypatch: pytest.MonkeyPatch
) -> Iterator[RunningServer]:
    monkeypatch.setattr(write, "READ_BACK_DELAYS", (0.01, 0.01, 0.01))
    with RunningServer(docmost.recorder.client()) as running:
        yield running


@pytest.fixture
def token(server: RunningServer) -> str:
    return server.token(scopes=("write",))


def _content(result: dict[str, Any]) -> Any:
    body = result["content"].split("\n", 1)[1].rsplit("\n", 1)[0]
    return json.loads(body)


def test_check_document_finds_what_docmost_would_drop() -> None:
    assert check_document(COLORED) == []
    assert check_document({"type": "paragraph"}) == [
        "The document must be an object with type 'doc'."
    ]
    problems = check_document(
        _doc(
            {"type": "heading", "content": [_para("nested")]},
            {"type": "bulletList", "content": []},
            {"type": "blink"},
            {"type": "paragraph", "content": [{"type": "text", "text": "x", "marks": [GLOW]}]},
            {"type": "listItem", "content": [_para("loose")]},
            {"type": "details", "content": [{"type": "detailsContent", "content": [_para("x")]}]},
            {"type": "paragraph", "content": [{"type": "text", "text": ""}]},
        )
    )  # fmt: skip
    assert problems == [
        "doc.content[0].content[0]: paragraph cannot be inside heading.",
        "doc.content[1]: a bulletList node needs content.",
        "doc.content[2]: unknown node type 'blink'.",
        "doc.content[3].content[0].marks[0]: unknown mark 'glow'.",
        "doc.content[4]: listItem cannot be inside doc.",
        "doc.content[5]: a details node must start with a detailsSummary node.",
        "doc.content[6].content[0]: a text node needs non-empty text.",
    ]


def test_outline_ignores_attributes_and_trailing_paragraphs() -> None:
    plain = _doc(_para("A"), {"type": "paragraph"})
    assert outline(plain) == outline(_doc(_para("A", textAlign="left")))
    assert outline(COLORED) == [
        ("doc", ""),
        ("heading", "Plan"),
        ("callout", ""),
        ("paragraph", "Red"),
    ]


def test_read_page_as_json(server: RunningServer, token: str, docmost: FakeDocmost) -> None:
    docmost.pages["p1"]["document"] = COLORED
    data = server.call(token, "get_page", {"page": "p1", "format": "json"})
    assert data["format"] == "json"
    assert data["truncated"] is False
    assert _content(data) == COLORED
    assert data["content"].startswith("<docmost-untrusted-content")


def test_json_too_large_is_refused(engine: AsyncEngine, docmost: FakeDocmost) -> None:
    docmost.pages["p1"]["document"] = _doc(_para("x" * 5000))
    with (
        RunningServer(docmost.recorder.client(), max_page_chars=1000) as running,
        pytest.raises(ToolError, match="more than the 5000"),
    ):
        running.call(running.token(), "get_page", {"page": "p1", "format": "json"})


def test_replace_and_restore_json(server: RunningServer, token: str, docmost: FakeDocmost) -> None:
    written = server.call(token, "replace_page_json", {"page": "p1", "document": COLORED})
    assert written["changed"] is True
    assert docmost.pages["p1"]["document"] == COLORED
    assert docmost.requests("pages/update")[-1]["format"] == "json"

    again = server.call(token, "replace_page_json", {"page": "p1", "document": COLORED})
    assert again["changed"] is False

    server.call(token, "replace_page_json", {"page": "p1", "document": _doc(_para("Later"))})
    restored = server.call(token, "restore_snapshot", {"snapshot_id": again["snapshot_id"]})
    assert restored["changed"] is True
    assert docmost.pages["p1"]["document"] == COLORED

    diff = server.call(token, "diff_page", {"page": "p1", "from_version": written["snapshot_id"]})
    assert "-Intro" in diff["diff"]
    assert "+Red" in diff["diff"]


def test_invalid_json_is_not_sent(server: RunningServer, token: str, docmost: FakeDocmost) -> None:
    bad = _doc({"type": "heading", "content": [_para("x")]})
    with pytest.raises(ToolError, match="paragraph cannot be inside heading"):
        server.call(token, "replace_page_json", {"page": "p1", "document": bad})
    assert not docmost.requests("pages/update")

    preview = server.call(
        token, "replace_page_json", {"page": "p1", "document": bad, "dry_run": True}
    )
    assert preview["problems"]
    assert preview["changed"] is False

    good = server.call(
        token, "replace_page_json", {"page": "p1", "document": COLORED, "dry_run": True}
    )
    assert good["problems"] == []
    assert "+Red" in good["diff"]
    assert not docmost.requests("pages/update")


def test_mangled_json_is_put_back(server: RunningServer, token: str, docmost: FakeDocmost) -> None:
    def drop_callouts(doc: dict[str, Any]) -> dict[str, Any]:
        return _doc(*(node for node in doc["content"] if node["type"] != "callout"))

    docmost.store_json = drop_callouts
    before = docmost.pages["p1"]["content"]
    with pytest.raises(ToolError, match="previous body was put back"):
        server.call(token, "replace_page_json", {"page": "p1", "document": COLORED})
    assert docmost.pages["p1"]["content"].strip() == before
    assert len(docmost.requests("pages/update")) == 2


def test_restore_page_version(server: RunningServer, token: str, docmost: FakeDocmost) -> None:
    restored = server.call(token, "restore_page_version", {"version_id": V1})
    assert restored["changed"] is True
    assert restored["restored_version_id"] == V1
    assert docmost.pages["p1"]["content"].strip() == "Old text"
    with pytest.raises(ToolError, match="not found"):
        server.call(token, "restore_page_version", {"version_id": str(uuid.uuid4())})


def test_restore_version_of_other_space(engine: AsyncEngine, docmost: FakeDocmost) -> None:
    docmost.add_version(V9, "p3", "x")
    with (
        RunningServer(docmost.recorder.client(), allowed_spaces="general") as running,
        pytest.raises(ToolError, match="Space not found"),
    ):
        running.call(running.token(scopes=("write",)), "restore_page_version", {"version_id": V9})


def test_json_tools_need_write(server: RunningServer) -> None:
    tools = server.tools(server.token())
    assert "replace_page_json" not in tools
    assert "restore_page_version" not in tools
