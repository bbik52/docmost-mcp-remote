"""Sections of a Markdown page body, found by their headings.

A section starts at an ATX heading (``#`` to ``######``) and runs until the
next heading of the same or a higher level, so it includes its subsections.
Text before the first heading is section 0. Headings inside fenced code
blocks are ignored. A section's hash lets a later edit check that nobody
changed the section in between.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass

_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


@dataclass(frozen=True, slots=True)
class Section:
    index: int
    #: 0 for the text before the first heading.
    level: int
    title: str
    #: Character offsets of the section in the body, end exclusive.
    start: int
    end: int
    text: str

    @property
    def hash(self) -> str:
        return section_hash(self.text)

    @property
    def heading_line(self) -> str:
        return self.text.split("\n", 1)[0] if self.level else ""


def section_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()[:16]


def _headings(markdown: str) -> list[tuple[int, int, str]]:
    """(offset, level, title) of every heading outside code blocks."""
    found: list[tuple[int, int, str]] = []
    fence: str | None = None
    offset = 0
    for line in markdown.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        fence_match = _FENCE.match(stripped)
        if fence is not None:
            if (
                fence_match
                and fence_match.group(1)[0] == fence[0]
                and len(fence_match.group(1)) >= len(fence)
            ):
                fence = None
        elif fence_match:
            fence = fence_match.group(1)
        else:
            heading = _HEADING.match(stripped)
            if heading:
                found.append((offset, len(heading.group(1)), (heading.group(2) or "").strip()))
        offset += len(line)
    return found


def split_sections(markdown: str) -> list[Section]:
    """Every section of ``markdown`` in document order, the preamble first if any."""
    headings = _headings(markdown)
    sections: list[Section] = []
    first = headings[0][0] if headings else len(markdown)
    if markdown[:first].strip():
        sections.append(Section(0, 0, "", 0, first, markdown[:first]))
    for number, (start, level, title) in enumerate(headings):
        end = next(
            (offset for offset, other, _ in headings[number + 1 :] if other <= level),
            len(markdown),
        )
        sections.append(Section(number + 1, level, title, start, end, markdown[start:end]))
    return sections


def find_section(markdown: str, index: int) -> Section | None:
    return next((item for item in split_sections(markdown) if item.index == index), None)


def replace_section(markdown: str, section: Section, new_text: str) -> str:
    """``markdown`` with ``section`` replaced by ``new_text``, blank lines kept around it."""
    before = markdown[: section.start].rstrip("\n")
    after = markdown[section.end :].lstrip("\n")
    parts = [part for part in (before, new_text.strip("\n"), after) if part]
    return "\n\n".join(parts) + ("\n" if markdown.endswith("\n") else "")


def apply_operation(current: str, content: str, operation: str) -> str:
    """The body Docmost is expected to end up with after a body update."""
    if operation == "append":
        return f"{current.rstrip()}\n\n{content.strip()}".strip()
    if operation == "prepend":
        return f"{content.strip()}\n\n{current.lstrip()}".strip()
    return content


def unified_diff(before: str, after: str, *, limit: int) -> tuple[str, bool]:
    """A unified diff of two bodies, cut to ``limit`` characters."""
    lines = difflib.unified_diff(
        before.splitlines(), after.splitlines(), "current", "proposed", lineterm="", n=2
    )
    text = "\n".join(lines)
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def outside_kept(updated: str, original: str, section: Section) -> bool:
    """Whether the text around ``section`` survived in ``updated``, ignoring whitespace."""
    squashed = _squash(updated)
    before = _squash(original[: section.start])
    after = _squash(original[section.end :])
    return squashed.startswith(before) and squashed.endswith(after)
