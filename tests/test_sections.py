from __future__ import annotations

from docmost_mcp_remote.sections import (
    apply_operation,
    find_section,
    outside_kept,
    replace_section,
    section_hash,
    split_sections,
    unified_diff,
)

BODY = """Intro line.

# Guide

Top text.

## Install

Run it.

```sh
# not a heading
```

## Use ##

Use it.

# Appendix

End.
"""


def test_split_sections() -> None:
    sections = split_sections(BODY)
    assert [(s.index, s.level, s.title) for s in sections] == [
        (0, 0, ""),
        (1, 1, "Guide"),
        (2, 2, "Install"),
        (3, 2, "Use"),
        (4, 1, "Appendix"),
    ]
    guide = sections[1]
    # A section runs to the next heading of the same or a higher level.
    assert guide.text.startswith("# Guide")
    assert "Use it." in guide.text
    assert "Appendix" not in guide.text
    assert "# not a heading" in sections[2].text
    assert sections[0].text == "Intro line.\n\n"


def test_no_preamble_and_no_headings() -> None:
    assert [s.index for s in split_sections("# Only\n\ntext")] == [1]
    only = split_sections("just text")
    assert [(s.index, s.level) for s in only] == [(0, 0)]
    assert split_sections("") == []


def test_tilde_fence_and_empty_heading() -> None:
    sections = split_sections("~~~\n# inside\n~~~\n\n#\n\nx")
    assert [(s.index, s.title) for s in sections] == [(0, ""), (1, "")]


def test_replace_section() -> None:
    install = find_section(BODY, 2)
    assert install is not None
    changed = replace_section(BODY, install, "## Install\n\nUse pip.")
    assert "Use pip." in changed
    assert "Run it." not in changed
    assert "Top text.\n\n## Install\n\nUse pip.\n\n## Use ##" in changed
    assert outside_kept(changed, BODY, install)
    assert not outside_kept(changed.replace("Intro", "Changed"), BODY, install)

    removed = replace_section(BODY, install, "")
    assert "Install" not in removed
    assert "Top text.\n\n## Use ##" in removed


def test_hash_ignores_surrounding_whitespace() -> None:
    assert section_hash("# A\n\nx\n\n") == section_hash("# A\n\nx")
    assert section_hash("# A\n\nx") != section_hash("# A\n\ny")


def test_apply_operation_and_diff() -> None:
    assert apply_operation("a", "b", "append") == "a\n\nb"
    assert apply_operation("a", "b", "prepend") == "b\n\na"
    assert apply_operation("a", "b", "replace") == "b"
    diff, truncated = unified_diff("one\ntwo", "one\nthree", limit=1000)
    assert "-two" in diff
    assert "+three" in diff
    assert truncated is False
    assert unified_diff("a", "b" * 100, limit=10)[1] is True
