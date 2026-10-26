"""Checks for ProseMirror documents written to Docmost as JSON.

Docmost does not refuse a document it cannot read: it drops unknown nodes
and stores what is left, which can leave a page broken. Documents are
therefore checked here before they are sent, and compared with what Docmost
stored afterwards.
"""

from __future__ import annotations

import re
from functools import cache
from typing import Any

_CELL = (
    "(paragraph | heading | bulletList | orderedList | taskList | blockquote | callout | image"
    " | video | audio | subpages | attachment | mathBlock | details | codeBlock)+"
)
_TRANSCLUDED = (
    "(paragraph | heading | blockquote | codeBlock | horizontalRule | bulletList | orderedList"
    " | taskList | image | video | audio | attachment | callout | details | embed | mathBlock"
    " | table | drawio | excalidraw | pdf | subpages | columns | youtube)+"
)
#: Content expression and groups of each node type in Docmost 0.97's editor
#: schema, read from Docmost with ``getSchema(tiptapExtensions)``. Older
#: releases know fewer types; the comparison after a write catches those.
NODE_SCHEMA: dict[str, tuple[str, str]] = {
    "paragraph": ("inline*", "block"),
    "codeBlock": ("text*", "block"),
    "mention": ("", "inline"),
    "blockquote": ("block+", "block"),
    "bulletList": ("listItem+", "block list"),
    "hardBreak": ("", "inline"),
    "horizontalRule": ("", "block"),
    "listItem": ("paragraph block*", ""),
    "orderedList": ("listItem+", "block list"),
    "text": ("", "inline"),
    "doc": ("block+ footnotes?", ""),
    "heading": ("inline*", "block"),
    "taskList": ("taskItem+", "block list"),
    "taskItem": ("paragraph block*", ""),
    "mathInline": ("", "inline"),
    "mathBlock": ("", "block"),
    "details": ("detailsSummary detailsContent", "block"),
    "detailsContent": ("block*", "block"),
    "detailsSummary": ("inline*", "block"),
    "tabs": ("tab+", "block"),
    "tab": ("tabLabel tabPanel", ""),
    "tabLabel": ("inline*", ""),
    "tabPanel": ("block+", ""),
    "table": ("tableRow+", "block"),
    "tableCell": (_CELL, ""),
    "tableRow": ("(tableCell | tableHeader)*", ""),
    "tableHeader": (_CELL, ""),
    "youtube": ("", "block"),
    "image": ("", "block"),
    "video": ("", "block"),
    "audio": ("", "block"),
    "pdf": ("", "block"),
    "pageBreak": ("", "block"),
    "callout": ("block+", "block"),
    "attachment": ("", "block"),
    "drawio": ("", "block"),
    "excalidraw": ("", "block"),
    "embed": ("", "block"),
    "subpages": ("", "block"),
    "columns": ("column+", "block"),
    "column": ("block+", "block"),
    "status": ("", "inline"),
    "transclusionSource": (_TRANSCLUDED, "block"),
    "transclusionReference": ("", "block"),
    "base": ("", "block"),
    "footnotes": ("footnote*", ""),
    "footnote": ("paragraph+", ""),
    "footnoteReference": ("text*", "inline"),
    "integrationCard": ("", "block"),
    "integrationMention": ("", "inline"),
}
NODE_TYPES = frozenset(NODE_SCHEMA)
MARK_TYPES = frozenset(
    {
        "link", "textStyle", "bold", "code", "italic", "strike", "underline", "comment",
        "superscript", "subscript", "highlight",
    }
)  # fmt: skip
_NAME = re.compile(r"[A-Za-z]+")
MAX_DEPTH = 64
MAX_NODES = 50_000


@cache
def _allowed(kind: str) -> frozenset[str]:
    """Node types that may appear directly inside ``kind``."""
    names: set[str] = set()
    for name in _NAME.findall(NODE_SCHEMA[kind][0]):
        if name in NODE_SCHEMA:
            names.add(name)
        names.update(node for node, (_, groups) in NODE_SCHEMA.items() if name in groups.split())
    return frozenset(names)


def _rule(kind: str) -> tuple[str | None, bool]:
    """The node type a ``kind`` must start with, and whether it needs any content."""
    expression = NODE_SCHEMA[kind][0].strip()
    tokens = expression.split()
    first = tokens[0] if len(tokens) > 1 and tokens[0] in NODE_SCHEMA else None
    needed = bool(expression) and (first is not None or not expression.endswith(("*", "?")))
    return first, needed


def check_document(doc: Any) -> list[str]:
    """Problems that would make Docmost drop or mangle part of ``doc``; empty if none."""
    problems: list[str] = []
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        return ["The document must be an object with type 'doc'."]
    count = 0

    def visit(node: Any, path: str, depth: int) -> None:
        nonlocal count
        count += 1
        if len(problems) >= 20 or count > MAX_NODES:
            return
        if depth > MAX_DEPTH:
            problems.append(f"{path}: nested deeper than {MAX_DEPTH} levels.")
            return
        if not isinstance(node, dict):
            problems.append(f"{path}: a node must be an object.")
            return
        kind = node.get("type")
        if kind not in NODE_TYPES:
            problems.append(f"{path}: unknown node type {kind!r}.")
            return
        if kind == "doc" and depth:
            problems.append(f"{path}: 'doc' can only be the top node.")
        attrs = node.get("attrs")
        if attrs is not None and not isinstance(attrs, dict):
            problems.append(f"{path}.attrs: must be an object.")
        marks = node.get("marks")
        if marks is not None:
            if not isinstance(marks, list):
                problems.append(f"{path}.marks: must be a list.")
            else:
                for index, mark in enumerate(marks):
                    if not isinstance(mark, dict) or mark.get("type") not in MARK_TYPES:
                        name = mark.get("type") if isinstance(mark, dict) else mark
                        problems.append(f"{path}.marks[{index}]: unknown mark {name!r}.")
        content = node.get("content")
        if kind == "text":
            if not isinstance(node.get("text"), str) or not node["text"]:
                problems.append(f"{path}: a text node needs non-empty text.")
            if content is not None:
                problems.append(f"{path}: a text node cannot have content.")
            return
        if content is not None and not isinstance(content, list):
            problems.append(f"{path}.content: must be a list of nodes.")
            return
        children = content or []
        allowed = _allowed(kind)
        first, needed = _rule(kind)
        if needed and not children:
            problems.append(f"{path}: a {kind} node needs content.")
        if (
            first
            and children
            and (not isinstance(children[0], dict) or children[0].get("type") != first)
        ):
            problems.append(f"{path}: a {kind} node must start with a {first} node.")
        for index, child in enumerate(children):
            child_type = child.get("type") if isinstance(child, dict) else None
            if child_type in NODE_TYPES and child_type not in allowed:
                problems.append(f"{path}.content[{index}]: {child_type} cannot be inside {kind}.")
                continue
            visit(child, f"{path}.content[{index}]", depth + 1)

    visit(doc, "doc", 0)
    if count > MAX_NODES:
        problems.append(f"The document has more than {MAX_NODES} nodes.")
    return problems


def outline(doc: Any) -> list[tuple[str, str]]:
    """Node types in document order, each with the text directly inside it.

    Attributes and marks are left out: Docmost adds defaults to both. Two
    documents with the same outline hold the same nodes and text.
    """
    found: list[tuple[str, str]] = []

    def visit(node: Any) -> None:
        if not isinstance(node, dict) or node.get("type") == "text":
            return
        content = node.get("content")
        children: list[Any] = content if isinstance(content, list) else []
        text = "".join(
            child.get("text", "")
            for child in children
            if isinstance(child, dict) and child.get("type") == "text"
        )
        found.append((str(node.get("type")), text))
        for child in children:
            visit(child)

    visit(doc)
    # An empty trailing paragraph is what an editor leaves at the end.
    while len(found) > 1 and found[-1] == ("paragraph", ""):
        found.pop()
    return found
