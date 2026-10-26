"""Suggestions and the page tree against real Docmost."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, MEMBER

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def server(migrated_database: str, tokens: dict[str, str]) -> Iterator[RunningServer]:
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as running:
        yield running


def test_tree_and_suggest(server: RunningServer) -> None:
    token = server.token(scopes=("write",), email=MEMBER[0], password=MEMBER[1])
    unique = uuid.uuid4().hex[:10]
    spaces = server.call(token, "list_spaces")["spaces"]
    general = next(space["id"] for space in spaces if space["slug"] == "general")

    def create(title: str, parent: str | None = None) -> str:
        args = {"space_id": general, "title": title}
        if parent:
            args["parent_page_id"] = parent
        return str(server.call(token, "create_page", args)["id"])

    root = create(f"Tree {unique}")
    child = create("Child", root)
    grandchild = create("Grandchild", child)

    tree = server.call(token, "get_page_tree", {"space_id": general, "root_page_id": root})
    assert tree["pages"][0]["id"] == child
    assert tree["pages"][0]["children"][0]["id"] == grandchild
    assert tree["truncated"] is False

    shallow = server.call(
        token, "get_page_tree", {"space_id": general, "root_page_id": root, "max_depth": 1}
    )
    assert shallow["not_expanded"] == [child]

    found = server.call(token, "suggest", {"query": f"Tree {unique}"})
    assert [page["id"] for page in found["pages"]] == [root]
    people = server.call(token, "suggest", {"query": "Member", "pages": False, "people": True})
    assert MEMBER[0] in {person["email"] for person in people["people"]}
