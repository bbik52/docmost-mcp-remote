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
