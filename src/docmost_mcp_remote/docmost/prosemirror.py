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


# Markdown from ProseMirror JSON, for page versions from Docmost's history, which
# are stored only as JSON. Unknown nodes keep their text so nothing is silently lost.

_MARK_WRAP = {"bold": "**", "italic": "_", "strike": "~~", "code": "`"}
_LISTS = frozenset({"bulletList", "orderedList", "taskList"})


def doc_to_markdown(doc: dict[str, Any]) -> str:
    """Render a Docmost ProseMirror document as Markdown."""
    blocks = _blocks(doc.get("content") or [])
    return "\n\n".join(block for block in blocks if block).strip() + "\n"


def _children(node: dict[str, Any]) -> list[dict[str, Any]]:
    return [child for child in node.get("content") or [] if isinstance(child, dict)]


def _attrs(node: dict[str, Any]) -> dict[str, Any]:
    attrs = node.get("attrs")
    return attrs if isinstance(attrs, dict) else {}


def _inline(nodes: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for node in nodes:
        node_type = node.get("type")
        if node_type == "text":
            parts.append(_marked(str(node.get("text", "")), node.get("marks") or []))
        elif node_type == "hardBreak":
            parts.append("  \n")
        elif node_type == "mention":
            attrs = _attrs(node)
            parts.append(f"@{attrs.get('label') or attrs.get('id') or ''}")
        elif node_type in ("mathInline", "mathBlock"):
            parts.append(f"${_attrs(node).get('text', '')}$")
        elif node_type == "image":
            attrs = _attrs(node)
            parts.append(f"![{attrs.get('alt') or ''}]({attrs.get('src') or ''})")
        else:
            parts.append(_inline(_children(node)))
    return "".join(parts)


def _marked(text: str, marks: list[Any]) -> str:
    if not text:
        return text
    names = {mark.get("type") for mark in marks if isinstance(mark, dict)}
    if "code" in names:
        text = f"`{text}`"
    else:
        for name in ("strike", "italic", "bold"):
            if name in names:
                wrap = _MARK_WRAP[name]
                stripped = text.strip()
                if stripped:
                    lead = text[: len(text) - len(text.lstrip())]
                    trail = text[len(text.rstrip()) :]
                    text = f"{lead}{wrap}{stripped}{wrap}{trail}"
    link = next(
        (mark for mark in marks if isinstance(mark, dict) and mark.get("type") == "link"), None
    )
    if link is not None:
        href = (link.get("attrs") or {}).get("href") or ""
        text = f"[{text}]({href})"
    return text


def _indent(text: str, prefix: str) -> str:
    lines = text.split("\n")
    pad = " " * len(prefix)
    return "\n".join(
        (prefix if index == 0 else (pad if line else "")) + line for index, line in enumerate(lines)
    )


def _blocks(nodes: list[dict[str, Any]]) -> list[str]:
    return [_block(node) for node in nodes]


def _block(node: dict[str, Any]) -> str:
    node_type = node.get("type")
    attrs = _attrs(node)
    children = _children(node)
    if node_type == "paragraph":
        return _inline(children)
    if node_type == "heading":
        raw = attrs.get("level")
        level = raw if isinstance(raw, int) else 1
        return f"{'#' * max(1, min(level, 6))} {_inline(children)}"
    if node_type == "blockquote":
        inner = "\n\n".join(_blocks(children))
        return "\n".join(f"> {line}" for line in inner.split("\n"))
    if node_type == "codeBlock":
        code = "".join(str(child.get("text", "")) for child in children)
        fence = "````" if "```" in code else "```"
        return f"{fence}{attrs.get('language') or ''}\n{code}\n{fence}"
    if node_type == "horizontalRule":
        return "---"
    if node_type in _LISTS:
        return _list(node_type, children, attrs.get("start"))
    if node_type == "table":
        return _table(children)
    if node_type == "image":
        return _inline([node])
    if node_type == "mathBlock":
        return f"$$\n{attrs.get('text', '')}\n$$"
    if node_type == "callout":
        inner = "\n\n".join(_blocks(children))
        kind = str(attrs.get("type") or "info")
        return f":::{kind}\n{inner}\n:::"
    if node_type in ("attachment", "video", "audio", "pdf"):
        name = attrs.get("name") or attrs.get("title") or node_type
        return f"[{name}]({attrs.get('url') or attrs.get('src') or ''})"
    if node_type in ("embed", "drawio", "excalidraw", "youtube"):
        return f"[{node_type}]({attrs.get('src') or attrs.get('url') or ''})"
    if children and all(child.get("type") == "text" for child in children):
        return _inline(children)
    # details, columns and other containers: their blocks in order.
    return "\n\n".join(block for block in _blocks(children) if block)


def _list(kind: str, items: list[dict[str, Any]], start: Any) -> str:
    number = start if isinstance(start, int) else 1
    lines: list[str] = []
    for item in items:
        if kind == "orderedList":
            prefix = f"{number}. "
            number += 1
        elif kind == "taskList":
            prefix = f"- [{'x' if _attrs(item).get('checked') else ' '}] "
        else:
            prefix = "- "
        inner = ""
        for child in _children(item):
            block = _block(child)
            if not block:
                continue
            separator = "\n" if child.get("type") in _LISTS else "\n\n"
            inner = f"{inner}{separator}{block}" if inner else block
        lines.append(_indent(inner, prefix))
    return "\n".join(lines)


def _cell(node: dict[str, Any]) -> str:
    text = " ".join(block for block in _blocks(_children(node)) if block)
    return text.replace("|", "\\|").replace("\n", " ")


def _table(rows: list[dict[str, Any]]) -> str:
    grid = [[_cell(cell) for cell in _children(row)] for row in rows]
    if not grid:
        return ""
    columns = max(len(row) for row in grid)
    grid = [row + [""] * (columns - len(row)) for row in grid]

    def line(cells: list[str]) -> str:
        # Same layout as Docmost's own Markdown: cells padded to three characters.
        return "| " + " | ".join(cell.ljust(3) for cell in cells) + " |"

    lines = [line(grid[0]), line(["---"] * columns)]
    lines.extend(line(row) for row in grid[1:])
    return "\n".join(lines)
