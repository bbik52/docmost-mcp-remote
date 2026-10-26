from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.fakes import docmost_routes, error, ok
from tests.harness import RunningServer
from tests.test_write_tools import FakeDocmost


class LabelledDocmost(FakeDocmost):
    """FakeDocmost with labels and backlinks."""

    def __init__(self, version: str = "0.97.0") -> None:
        self.labels: dict[str, set[str]] = {"p1": {"draft"}}
        self.version = version
        super().__init__()

    def routes(self) -> dict[str, Any]:
        routes = super().routes()
        routes.update(docmost_routes(version=self.version))

        def body(request: httpx.Request) -> dict[str, Any]:
            return dict(json.loads(request.content))

        def label(name: str) -> dict[str, str]:
            return {"id": f"id-{name}", "name": name, "type": "page"}

        def page_labels(request: httpx.Request) -> httpx.Response:
            names = sorted(self.labels.get(body(request)["pageId"], set()))
            return ok({"items": [label(name) for name in names], "meta": {}})

        def all_labels(request: httpx.Request) -> httpx.Response:
            names = sorted(set().union(*self.labels.values()))
            return ok({"items": [label(name) for name in names], "meta": {}})

        def add(request: httpx.Request) -> httpx.Response:
            data = body(request)
            names = [name.lower() for name in data["names"]]
            self.labels.setdefault(data["pageId"], set()).update(names)
            return ok([label(name) for name in names])

        def remove(request: httpx.Request) -> httpx.Response:
            data = body(request)
            self.labels[data["pageId"]].discard(data["labelId"].removeprefix("id-"))
            return httpx.Response(200, json={"success": True, "status": 200})

        def by_label(request: httpx.Request) -> httpx.Response:
            name = body(request)["name"]
            items = [
                {**self.pages[page_id], "space": {"id": self.pages[page_id]["spaceId"]}}
                for page_id, names in self.labels.items()
                if name in names
            ]
            return ok({"items": items, "meta": {}})

        def backlinks(request: httpx.Request) -> httpx.Response:
            data = body(request)
            linked = ["p2", "p3"] if data["direction"] == "incoming" else []
            return ok({"items": [self.pages[page_id] for page_id in linked], "meta": {}})

        def search(request: httpx.Request) -> httpx.Response:
            return ok({"items": [{**self.pages["p1"], "space": {"id": "s1"}}]})

        routes.update(
            {
                "/api/pages/labels": page_labels,
                "/api/labels": all_labels,
                "/api/pages/labels/add": add,
                "/api/pages/labels/remove": remove,
                "/api/labels/pages": by_label,
                "/api/pages/backlinks": backlinks,
                "/api/search": search,
            }
        )
        return routes


@pytest.fixture
def docmost() -> LabelledDocmost:
    return LabelledDocmost()


@pytest.fixture
def server(engine: AsyncEngine, docmost: LabelledDocmost) -> Iterator[RunningServer]:
    with RunningServer(docmost.recorder.client()) as running:
        yield running


@pytest.fixture
def token(server: RunningServer) -> str:
    return server.token(scopes=("write",))


def test_labels(server: RunningServer, token: str, docmost: LabelledDocmost) -> None:
    added = server.call(token, "add_labels", {"page": "p1", "labels": ["Team-A", "spec"]})
    assert [item["name"] for item in added["labels"]] == ["draft", "spec", "team-a"]
    assert docmost.requests("pages/labels/add")[-1] == {"pageId": "p1", "names": ["Team-A", "spec"]}

    listed = server.call(token, "list_labels", {"page": "p1"})
    assert [item["name"] for item in listed["labels"]] == ["draft", "spec", "team-a"]
    assert len(server.call(token, "list_labels")["labels"]) == 3

    pages = server.call(token, "find_pages_by_label", {"label": "Spec"})
    assert [item["id"] for item in pages["pages"]] == ["p1"]

    removed = server.call(token, "remove_label", {"page": "p1", "label": "draft"})
    assert removed["removed"] == "draft"
    assert docmost.requests("pages/labels/remove")[-1] == {"pageId": "p1", "labelId": "id-draft"}
    with pytest.raises(ToolError, match="no label 'draft'"):
        server.call(token, "remove_label", {"page": "p1", "label": "draft"})


def test_invalid_label_name(server: RunningServer, token: str) -> None:
    with pytest.raises(ToolError):
        server.call(token, "add_labels", {"page": "p1", "labels": ["two words"]})


def test_backlinks(server: RunningServer, token: str) -> None:
    incoming = server.call(token, "list_backlinks", {"page": "p1"})
    assert [item["id"] for item in incoming["pages"]] == ["p2", "p3"]
    outgoing = server.call(token, "list_backlinks", {"page": "p1", "direction": "outgoing"})
    assert outgoing["pages"] == []


def test_search_filters(server: RunningServer, token: str, docmost: LabelledDocmost) -> None:
    server.call(
        token,
        "search",
        {"query": "guide", "title_only": True, "labels": ["Draft"], "created_by_me": True},
    )
    assert docmost.requests("search")[-1] == {
        "query": "guide",
        "limit": 20,
        "titleOnly": True,
        "labelIds": ["id-draft"],
        "creatorId": "docmost-user-1",
    }
    with pytest.raises(ToolError, match="Unknown labels: nope"):
        server.call(token, "search", {"query": "guide", "labels": ["nope"]})


def test_restricted_spaces(engine: AsyncEngine, docmost: LabelledDocmost) -> None:
    with RunningServer(docmost.recorder.client(), allowed_spaces="general") as server:
        token = server.token(scopes=("write",))
        incoming = server.call(token, "list_backlinks", {"page": "p1"})
        assert [item["id"] for item in incoming["pages"]] == ["p2"]
        for tool, arguments in (
            ("add_labels", {"page": "p3", "labels": ["x"]}),
            ("list_labels", {"page": "p3"}),
            ("find_pages_by_label", {"label": "x", "space_id": "s2"}),
        ):
            with pytest.raises(ToolError, match="not found"):
                server.call(token, tool, arguments)


def test_old_docmost(engine: AsyncEngine) -> None:
    docmost = LabelledDocmost(version="0.80.2")
    with RunningServer(docmost.recorder.client()) as server:
        token = server.token(scopes=("write",))
        for tool, arguments in (
            ("list_backlinks", {"page": "p1"}),
            ("list_labels", {}),
            ("add_labels", {"page": "p1", "labels": ["x"]}),
            ("search", {"query": "x", "title_only": True}),
        ):
            with pytest.raises(ToolError, match=r"needs Docmost 0\.\d+\.0 or newer .* 0\.80\.2"):
                server.call(token, tool, arguments)
        # Filters every supported release knows still work.
        server.call(token, "search", {"query": "x", "created_by_me": True})
    assert docmost.requests("pages/labels/add") == []


def test_missing_endpoint_is_explained(engine: AsyncEngine) -> None:
    docmost = LabelledDocmost(version="")
    docmost.recorder.routes["/api/pages/backlinks"] = error(404, "Cannot POST /api/pages/backlinks")
    with RunningServer(docmost.recorder.client()) as server:
        token = server.token()
        with pytest.raises(ToolError, match="does not offer this"):
            server.call(token, "list_backlinks", {"page": "p1"})
