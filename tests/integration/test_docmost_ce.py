"""The CE client against a real Docmost (see conftest.py)."""

from __future__ import annotations

import asyncio

import pytest

from docmost_mcp_remote.docmost import (
    CeDocmostClient,
    DocmostAuthError,
    DocmostNotFoundError,
)
from docmost_mcp_remote.docmost.ce import CeDocmostSession
from tests.integration.conftest import OWNER

pytestmark = pytest.mark.integration


async def _body_contains(session: CeDocmostSession, page_id: str, text: str) -> str:
    """Read the page until ``text`` shows up; writes are applied asynchronously."""
    content = ""
    for _ in range(20):
        content = (await session.get_page(page_id)).content
        if text in content:
            return content
        await asyncio.sleep(0.5)
    raise AssertionError(f"{text!r} not in page body: {content!r}")


async def test_version_is_supported(owner: CeDocmostSession) -> None:
    check = await owner.version()
    if check.version is None:
        pytest.skip("Docmost did not report its version: its request to GitHub failed")
    assert check.tested, f"Docmost {check.version} is newer than the tested range"


async def test_login(client: CeDocmostClient) -> None:
    session = client.session(await client.login(*OWNER))
    user = await session.current_user()
    assert user.email == OWNER[0]

    with pytest.raises(DocmostAuthError):
        await client.login(OWNER[0], "wrong-password")


async def test_invalid_token(client: CeDocmostClient) -> None:
    with pytest.raises(DocmostAuthError):
        await client.session("not-a-token").current_user()


async def test_page_lifecycle(owner: CeDocmostSession, space_id: str, unique: str) -> None:
    page = await owner.create_page(space_id, f"Page {unique}", markdown="# Hi\n\nFirst **bold**.")
    assert (await owner.get_page(page.id)).content.startswith("# Hi")

    await owner.update_page_body(page.id, f"Appended {unique}.", "append")
    body = await _body_contains(owner, page.id, f"Appended {unique}.")
    assert body.index("First") < body.index("Appended")

    await owner.update_page_body(page.id, "Prepended.", "prepend")
    body = await _body_contains(owner, page.id, "Prepended.")
    assert body.index("Prepended.") < body.index("First")

    await owner.update_page_body(page.id, f"# Replaced {unique}\n\n- a\n- b", "replace")
    body = await _body_contains(owner, page.id, f"Replaced {unique}")
    assert "First" not in body

    await owner.rename_page(page.id, f"Renamed {unique}")
    assert (await owner.get_page(page.id)).title == f"Renamed {unique}"

    by_slug = await owner.get_page(page.slug_id)
    assert by_slug.id == page.id


async def test_tree_and_breadcrumbs(owner: CeDocmostSession, space_id: str, unique: str) -> None:
    parent = await owner.create_page(space_id, f"Parent {unique}")
    child = await owner.create_page(space_id, f"Child {unique}", parent_page_id=parent.id)

    roots = await owner.list_pages(space_id, limit=100)
    assert any(item.id == parent.id for item in roots.items)
    children = await owner.list_pages(space_id, parent_page_id=parent.id)
    assert [item.id for item in children.items] == [child.id]

    trail = await owner.breadcrumbs(child.id)
    assert [item.id for item in trail] == [parent.id, child.id]

    # Moving needs a valid fractional-index position; reuse the child's own key.
    position = children.items[0].position
    assert position is not None
    await owner.move_page(child.id, parent_page_id=None, position=position)
    assert (await owner.get_page(child.id)).parent_page_id is None


async def test_recent_pages_paginate(owner: CeDocmostSession, space_id: str, unique: str) -> None:
    for index in range(3):
        await owner.create_page(space_id, f"Recent {unique} {index}")

    first = await owner.recent_pages(space_id=space_id, limit=2)
    assert len(first.items) == 2
    assert first.has_next_page
    second = await owner.recent_pages(space_id=space_id, limit=2, cursor=first.next_cursor)
    assert {item.id for item in first.items}.isdisjoint(item.id for item in second.items)


async def test_search(owner: CeDocmostSession, space_id: str, unique: str) -> None:
    page = await owner.create_page(space_id, "Searchable", markdown=f"needle{unique} here")
    for _ in range(20):
        hits = await owner.search(f"needle{unique}", space_id=space_id)
        if hits:
            break
        await asyncio.sleep(0.5)
    assert [hit.id for hit in hits] == [page.id]


async def test_comments(owner: CeDocmostSession, space_id: str, unique: str) -> None:
    page = await owner.create_page(space_id, f"Commented {unique}")
    top = await owner.create_comment(page.id, "Line one\nline two\n\nSecond paragraph")
    reply = await owner.create_comment(page.id, "A reply", parent_comment_id=top.id)

    comments = await owner.list_comments(page.id)
    by_id = {comment.id: comment for comment in comments.items}
    assert by_id[top.id].text == "Line one\nline two\n\nSecond paragraph"
    assert by_id[reply.id].parent_comment_id == top.id


async def test_trash_and_restore(owner: CeDocmostSession, space_id: str, unique: str) -> None:
    page = await owner.create_page(space_id, f"Trashed {unique}")

    await owner.move_to_trash(page.id)
    trash = await owner.list_trash(space_id, limit=100)
    assert any(item.id == page.id for item in trash.items)

    await owner.restore_from_trash(page.id)
    trash = await owner.list_trash(space_id, limit=100)
    assert all(item.id != page.id for item in trash.items)
    assert (await owner.get_page(page.id)).title == f"Trashed {unique}"


async def test_member_cannot_see_private_space(
    client: CeDocmostClient, owner: CeDocmostSession, member: CeDocmostSession, unique: str
) -> None:
    created = await client.call(
        "spaces/create", {"name": f"Private {unique}", "slug": f"p{unique}"}, _token(owner)
    )
    page = await owner.create_page(created["id"], "Hidden", markdown=f"hidden{unique}")

    with pytest.raises(DocmostNotFoundError):
        await member.get_page(page.id)
    with pytest.raises(DocmostNotFoundError):
        await member.update_page_body(page.id, "x", "append")
    assert await member.search(f"hidden{unique}") == []


def _token(session: CeDocmostSession) -> str:
    return session._token


SAMPLE = """# Title

Text with **bold**, _italic_, ~~strike~~, `code` and [a link](https://example.com).

- one
- two
  - nested

1. first
2. second

- [ ] todo
- [x] done

> quoted

```python
print("hi")
```

---

| Name | Value |
| --- | --- |
| a   | 1   |
"""


async def test_converted_markdown_matches_docmost(
    owner: CeDocmostSession, space_id: str, unique: str
) -> None:
    page = await owner.create_page(space_id, f"Convert {unique}", markdown=SAMPLE)
    docmost = (await owner.get_page(page.id)).content
    ours = await owner.get_page_document(page.id)
    assert ours.strip() == docmost.strip()


async def test_page_history(owner: CeDocmostSession, space_id: str, unique: str) -> None:
    page = await owner.create_page(space_id, f"History {unique}", markdown="First version")
    await owner.update_page_body(page.id, f"Second {unique}", "append")
    await _body_contains(owner, page.id, f"Second {unique}")
    # Docmost saves a version about a minute after the last edit of a new page.
    versions = []
    for _ in range(90):
        versions = (await owner.page_history(page.id)).items
        if versions:
            break
        await asyncio.sleep(2)
    assert versions, "Docmost saved no page version"
    version = await owner.history_version(versions[0].id)
    assert version.page_id == page.id
    assert f"Second {unique}" in version.content
