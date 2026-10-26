"""Links between Docmost pages in Markdown sent to Docmost.

Docmost records a backlink only for a link mark with ``internal: true``. Its
Markdown import never sets that, but it keeps inline HTML, and the link mark
reads ``data-internal="true"`` from an ``<a>`` tag. Links to pages of the same
Docmost are therefore rewritten to that tag before a body is sent.
"""

from __future__ import annotations

import re

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_CODE_SPAN = re.compile(r"(`+)(?:.+?)\1", re.DOTALL)
_LINK = re.compile(r"(?<![!\\])\[([^\[\]\n]+)\]\(\s*<?([^\s()<>]+)>?\s*\)")


def _page_path(base_url: str) -> re.Pattern[str]:
    # The same shape as Docmost's INTERNAL_LINK_REGEX, limited to this Docmost.
    return re.compile(rf"^(?:{re.escape(base_url.rstrip('/'))})?(?:/s/[^/\s]+)?/p/[A-Za-z0-9-]+/?$")


def mark_internal_links(markdown: str, base_url: str) -> str:
    """Rewrite Markdown links to pages of this Docmost as internal links."""
    page_path = _page_path(base_url)

    def link(match: re.Match[str]) -> str:
        text, href = match.group(1), match.group(2)
        if not page_path.match(href):
            return match.group(0)
        return f'<a href="{href}" data-internal="true">{text}</a>'

    def inline(text: str) -> str:
        out: list[str] = []
        last = 0
        for span in _CODE_SPAN.finditer(text):
            out.append(_LINK.sub(link, text[last : span.start()]))
            out.append(span.group(0))
            last = span.end()
        out.append(_LINK.sub(link, text[last:]))
        return "".join(out)

    lines = markdown.split("\n")
    result: list[str] = []
    chunk: list[str] = []
    fence: str | None = None
    for line in lines:
        opened = _FENCE.match(line)
        if fence is None and opened:
            if chunk:
                result.append(inline("\n".join(chunk)))
                chunk = []
            fence = opened.group(1)[0] * len(opened.group(1))
            result.append(line)
        elif fence is not None:
            if line.strip().startswith(fence) and set(line.strip()) == {fence[0]}:
                fence = None
            result.append(line)
        else:
            chunk.append(line)
    if chunk:
        result.append(inline("\n".join(chunk)))
    return "\n".join(result)
