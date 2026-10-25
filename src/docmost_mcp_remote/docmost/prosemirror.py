"""Minimal conversion between plain text and ProseMirror JSON documents.

Docmost stores comments as ProseMirror JSON. Comments written through this
server are plain text: one paragraph per block separated by a blank line,
single newlines become hard breaks.
"""

from __future__ import annotations

import re
from typing import Any


def text_to_doc(text: str) -> dict[str, Any]:
    paragraphs: list[dict[str, Any]] = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        content: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            if index:
                content.append({"type": "hardBreak"})
            if line:
                content.append({"type": "text", "text": line})
        paragraphs.append(
            {"type": "paragraph", "content": content} if content else {"type": "paragraph"}
        )
    return {"type": "doc", "content": paragraphs}


_BLOCK_TYPES = frozenset(
    {"paragraph", "heading", "blockquote", "codeBlock", "listItem", "taskItem", "callout"}
)


def doc_to_text(node: dict[str, Any]) -> str:
    """Flatten a ProseMirror node to plain text, blocks separated by a blank line."""
    parts: list[str] = []
    _collect(node, parts)
    return re.sub(r"\n{3,}", "\n\n", "".join(parts)).strip()


def _collect(node: dict[str, Any], parts: list[str]) -> None:
    node_type = node.get("type")
    if node_type == "text":
        parts.append(str(node.get("text", "")))
        return
    if node_type == "hardBreak":
        parts.append("\n")
        return
    if node_type == "mention":
        attrs = node.get("attrs") or {}
        parts.append(f"@{attrs.get('label') or attrs.get('id') or ''}")
        return
    for child in node.get("content") or []:
        if isinstance(child, dict):
            _collect(child, parts)
    if node_type in _BLOCK_TYPES:
        parts.append("\n\n")
