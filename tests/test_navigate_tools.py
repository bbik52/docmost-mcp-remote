from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.fakes import Handler, Recorder, docmost_routes, ok
from tests.harness import RunningServer

GENERAL = {"id": "s1", "name": "General", "slug": "general", "membership": {"role": "writer"}}
SECRET = {"id": "s2", "name": "Secret", "slug": "secret", "membership": {"role": "reader"}}

#: parent -> children; "big" has 150 children, read in two Docmost pages.
TREE: dict[str | None, list[str]] = {
    None: ["a", "b"],
    "a": ["a1", "a2"],
    "a1": ["a1x"],
    "a1x": ["deep"],
    "b": [f"b{i}" for i in range(150)],
}


def _routes() -> dict[str, Handler | httpx.Response]:
    routes = docmost_routes()

    def sidebar(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        kids = TREE.get(body.get("pageId"), [])
        start = int(body.get("cursor") or 0)
        chunk = kids[start : start + body["limit"]]
        more = start + len(chunk) < len(kids)
        items = [
            {
                "id": kid,
                "slugId": f"{kid}0000000000"[:10],
                "title": kid.upper(),
                "spaceId": "s1",
                "hasChildren": kid in TREE,
            }
            for kid in chunk
        ]
        meta = {"hasNextPage": more, "nextCursor": str(start + len(chunk)) if more else None}
        return ok({"items": items, "meta": meta})

    def page(page_id: str, space: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": page_id,
            "slugId": f"{page_id}000000000"[:10],
            "title": page_id,
            "spaceId": space["id"],
            "space": {"id": space["id"], "name": space["name"], "slug": space["slug"]},
        }

    routes.update(
        {
            "/api/spaces": ok({"items": [GENERAL, SECRET], "meta": {"hasNextPage": False}}),
            "/api/pages/sidebar-pages": sidebar,
            "/api/search/suggest": ok(
                {
                    "users": [{"id": "u1", "name": "Anna", "email": "anna@example.com"}],
                    "groups": [{"id": "g1", "name": "Editors", "description": None}],
                    "pages": [page("p1", GENERAL), page("p2", SECRET)],
                }
            ),
        }
    )
    return routes


@pytest.fixture
def mock() -> Recorder:
    return Recorder(_routes())


@pytest.fixture
def server(engine: AsyncEngine, mock: Recorder) -> Iterator[RunningServer]:
    with RunningServer(mock.client()) as running:
        yield running


@pytest.fixture
def restricted(engine: AsyncEngine, mock: Recorder) -> Iterator[RunningServer]:
    with RunningServer(mock.client(), allowed_spaces="general") as running:
        yield running


def test_suggest(server: RunningServer, mock: Recorder) -> None:
    data = server.call(server.token(), "suggest", {"query": "an", "people": True})
    assert [page["id"] for page in data["pages"]] == ["p1", "p2"]
    assert data["people"] == [{"id": "u1", "name": "Anna", "email": "anna@example.com"}]
    assert "groups" not in data
    assert mock.body() == {
        "query": "an",
        "includePages": True,
        "includeUsers": True,
        "includeGroups": False,
        "limit": 10,
    }


def test_suggest_allowed_spaces(restricted: RunningServer) -> None:
    token = restricted.token()
    data = restricted.call(token, "suggest", {"query": "p"})
    assert [page["id"] for page in data["pages"]] == ["p1"]
    with pytest.raises(ToolError, match="Space not found"):
        restricted.call(token, "suggest", {"query": "p", "space_id": "s2"})


def test_tree_depth(server: RunningServer) -> None:
    data = server.call(server.token(), "get_page_tree", {"space_id": "s1", "max_depth": 2})
    a, b = data["pages"]
    assert [child["id"] for child in a["children"]] == ["a1", "a2"]
    assert a["children"][0]["children"] == []
    assert len(b["children"]) == 150
    assert data["page_count"] == 154
    assert data["not_expanded"] == ["a1"]
    assert data["truncated"] is True


def test_tree_page_limit_and_root(server: RunningServer) -> None:
    token = server.token()
    data = server.call(token, "get_page_tree", {"space_id": "s1", "max_pages": 10})
    assert data["page_count"] == 10
    assert data["truncated"] is True
    assert "b" in data["not_expanded"]

    below = server.call(token, "get_page_tree", {"space_id": "s1", "root_page_id": "a1"})
    assert below["pages"] == [
        {
            "id": "a1x",
            "slug_id": "a1x0000000",
            "title": "A1X",
            "children": [{"id": "deep", "slug_id": "deep000000", "title": "DEEP", "children": []}],
        }
    ]
    assert below["truncated"] is False


def test_tree_allowed_spaces(restricted: RunningServer) -> None:
    with pytest.raises(ToolError, match="Space not found"):
        restricted.call(restricted.token(), "get_page_tree", {"space_id": "s2"})
