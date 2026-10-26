"""Where uploaded files go in a page body, and the editor nodes that show them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from docmost_mcp_remote.docmost.models import Attachment
from docmost_mcp_remote.docmost.prosemirror import doc_to_text


def file_node(item: Attachment) -> dict[str, Any]:
    """The editor node that shows an uploaded file in a page."""
    src = f"/api/files/{item.id}/{quote(item.file_name)}"
    if (item.mime_type or "").startswith("image/"):
        attrs: dict[str, Any] = {"src": src, "attachmentId": item.id, "alt": item.file_name}
        if item.file_size is not None:
            attrs["size"] = item.file_size
        return {"type": "image", "attrs": attrs}
    return {
        "type": "attachment",
        "attrs": {
            "url": src,
            "name": item.file_name,
            "mime": item.mime_type,
            "size": item.file_size,
            "attachmentId": item.id,
        },
    }


@dataclass(frozen=True, slots=True)
class Placement:
    """End of the page, end of the section under a heading, or after a block with some text."""

    after_heading: str | None = None
    after_text: str | None = None

    def describe(self) -> str:
        if self.after_heading:
            return f'at the end of the section "{self.after_heading}"'
        if self.after_text:
            return f'after the paragraph with "{self.after_text}"'
        return "at the end of the page"

    def as_dict(self) -> dict[str, str]:
        found = {"after_heading": self.after_heading, "after_text": self.after_text}
        return {key: value for key, value in found.items() if value}


def _same(left: str, right: str) -> bool:
    return " ".join(left.split()).casefold() == " ".join(right.split()).casefold()


def _is_blank(node: dict[str, Any]) -> bool:
    return node.get("type") == "paragraph" and not node.get("content")


def insertion_index(body: list[dict[str, Any]], placement: Placement) -> int | None:
    """Where in the top-level nodes the files go; None when the heading or text is not there."""
    if placement.after_heading:
        start = next(
            (
                index
                for index, node in enumerate(body)
                if node.get("type") == "heading"
                and _same(doc_to_text(node), placement.after_heading)
            ),
            None,
        )
        if start is None:
            return None
        level = int((body[start].get("attrs") or {}).get("level") or 1)
        end = next(
            (
                index
                for index in range(start + 1, len(body))
                if body[index].get("type") == "heading"
                and int((body[index].get("attrs") or {}).get("level") or 1) <= level
            ),
            len(body),
        )
    elif placement.after_text:
        wanted = " ".join(placement.after_text.split()).casefold()
        found = next(
            (
                index
                for index, node in enumerate(body)
                if wanted in " ".join(doc_to_text(node).split()).casefold()
            ),
            None,
        )
        if found is None:
            return None
        return found + 1
    else:
        end = len(body)
    # Empty paragraphs at the end of a section are spacing; the files go before them.
    while end > 0 and _is_blank(body[end - 1]):
        end -= 1
    return end


def place_files(
    document: dict[str, Any], nodes: list[dict[str, Any]], placement: Placement
) -> tuple[dict[str, Any], bool]:
    """The document with ``nodes`` inserted, and whether the place was found.

    When the heading or text is gone, the files go to the end of the page.
    """
    body = [node for node in document.get("content") or [] if isinstance(node, dict)]
    index = insertion_index(body, placement)
    found = index is not None
    if index is None:
        index = insertion_index(body, Placement()) or 0
    content = [*body[:index], *nodes, *body[index:]]
    return {**document, "type": "doc", "content": content}, found
