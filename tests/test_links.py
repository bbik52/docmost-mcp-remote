from __future__ import annotations

from docmost_mcp_remote.docmost.links import mark_internal_links

BASE = "https://docs.example.com"


def test_links_to_pages_become_internal() -> None:
    markdown = (
        "See [one](https://docs.example.com/s/general/p/abc123DEF0) and [two](/p/xyz-1).\n"
        "Not [other](https://elsewhere.example.com/s/general/p/abc123DEF0), "
        "[space](https://docs.example.com/s/general) or ![img](/p/abc).\n"
        "Code `[one](/p/abc)` stays.\n"
        "```\n[one](/p/abc)\n```\n"
        "After [three](/s/x/p/q1)"
    )
    assert mark_internal_links(markdown, BASE + "/") == (
        'See <a href="https://docs.example.com/s/general/p/abc123DEF0" data-internal="true">'
        'one</a> and <a href="/p/xyz-1" data-internal="true">two</a>.\n'
        "Not [other](https://elsewhere.example.com/s/general/p/abc123DEF0), "
        "[space](https://docs.example.com/s/general) or ![img](/p/abc).\n"
        "Code `[one](/p/abc)` stays.\n"
        "```\n[one](/p/abc)\n```\n"
        'After <a href="/s/x/p/q1" data-internal="true">three</a>'
    )


def test_text_without_links_is_unchanged() -> None:
    markdown = "# Title\n\n~~~python\nx = [1](2)\n~~~\n\nplain [a](https://example.com)"
    assert mark_internal_links(markdown, BASE) == markdown
