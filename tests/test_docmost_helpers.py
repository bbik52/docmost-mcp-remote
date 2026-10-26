from __future__ import annotations

import pytest

from docmost_mcp_remote.docmost.prosemirror import doc_to_text, text_to_doc
from docmost_mcp_remote.docmost.version import Version, parse_version


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0.97.0", Version(0, 97, 0)),
        ("v0.70.3", Version(0, 70, 3)),
        ("0.97.0-beta.2", Version(0, 97, 0)),
    ],
)
def test_parse_version(text: str, expected: Version) -> None:
    assert parse_version(text) == expected


@pytest.mark.parametrize("text", ["", "latest", "0.97"])
def test_parse_version_rejects(text: str) -> None:
    with pytest.raises(ValueError, match="not a Docmost version"):
        parse_version(text)


def test_text_round_trip() -> None:
    text = "First line\nsecond line\n\nNew paragraph"
    doc = text_to_doc(text)

    assert [node["type"] for node in doc["content"]] == ["paragraph", "paragraph"]
    assert doc_to_text(doc) == text


def test_doc_to_text_handles_mentions_and_nesting() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": "ask "},
                                    {"type": "mention", "attrs": {"label": "Anna"}},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    assert doc_to_text(doc) == "ask @Anna"


def test_doc_to_markdown() -> None:
    from docmost_mcp_remote.docmost.prosemirror import doc_to_markdown

    def text(value: str, *marks: str, href: str | None = None) -> dict[str, object]:
        node: dict[str, object] = {"type": "text", "text": value}
        node_marks: list[dict[str, object]] = [{"type": mark} for mark in marks]
        if href:
            node_marks.append({"type": "link", "attrs": {"href": href}})
        if node_marks:
            node["marks"] = node_marks
        return node

    def para(*content: dict[str, object]) -> dict[str, object]:
        return {"type": "paragraph", "content": list(content)}

    doc = {
        "type": "doc",
        "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [text("Title")]},
            para(
                text("a "),
                text("bold", "bold"),
                text(" "),
                text("it", "italic"),
                text(" "),
                text("site", href="https://example.com"),
                {"type": "hardBreak"},
                text("next"),
            ),
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            para(text("one")),
                            {
                                "type": "orderedList",
                                "content": [{"type": "listItem", "content": [para(text("sub"))]}],
                            },
                        ],
                    }
                ],
            },
            {
                "type": "taskList",
                "content": [
                    {
                        "type": "taskItem",
                        "attrs": {"checked": True},
                        "content": [para(text("done"))],
                    }
                ],
            },
            {"type": "codeBlock", "attrs": {"language": "sh"}, "content": [text("ls")]},
            {"type": "blockquote", "content": [para(text("q"))]},
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {"type": "tableHeader", "content": [para(text("Name"))]},
                            {"type": "tableHeader", "content": [para(text("V"))]},
                        ],
                    },
                    {
                        "type": "tableRow",
                        "content": [
                            {"type": "tableCell", "content": [para(text("a|b"))]},
                            {"type": "tableCell", "content": [para(text("1"))]},
                        ],
                    },
                ],
            },
            {"type": "unknownBlock", "content": [para(text("kept"))]},
        ],
    }
    assert doc_to_markdown(doc) == (
        "## Title\n\n"
        "a **bold** _it_ [site](https://example.com)  \nnext\n\n"
        "- one\n  1. sub\n\n"
        "- [x] done\n\n"
        "```sh\nls\n```\n\n"
        "> q\n\n"
        "| Name | V   |\n| --- | --- |\n| a\\|b | 1   |\n\n"
        "kept\n"
    )
