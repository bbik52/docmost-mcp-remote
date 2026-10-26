from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.docmost.prosemirror import text_to_doc
from docmost_mcp_remote.tools.health import is_empty, page_links
from tests.fakes import Recorder, docmost_routes, error, ok
from tests.harness import RunningServer

BASE = "https://docs.example.com"
GENERAL = {"id": "s1", "name": "General", "slug": "general", "membership": {"role": "writer"}}
SECRET = {"id": "s2", "name": "Secret", "slug": "secret", "membership": {"role": "reader"}}


def _linked(text: str, href: str) -> dict[str, Any]:
    mark = {"type": "link", "attrs": {"href": href}}
    return {"type": "paragraph", "content": [{"type": "text", "text": text, "marks": [mark]}]}


def _mention(slug_id: str, label: str) -> dict[str, Any]:
    attrs = {"entityType": "page", "slugId": slug_id, "label": label}
    return {"type": "paragraph", "content": [{"type": "mention", "attrs": attrs}]}


def _doc(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {"type": "doc", "content": list(nodes)}


def _page(page_id: str, title: str, days_ago: int, editor: str) -> dict[str, Any]:
    return {
        "id": page_id,
        "slugId": f"{page_id}slug00000"[:10],
        "title": title,
        "spaceId": "s1",
        "updatedAt": (datetime.now(UTC) - timedelta(days=days_ago)).isoformat(),
        "lastUpdatedById": editor,
    }


PAGES = [
    _page("p1", "Guide", 1, "u1"),
    _page("p2", "Guide", 2, "u1"),
    _page("p3", "", 3, "u2"),
    _page("p4", "Old notes", 400, "u2"),
    _page("p5", "Links", 5, "u1"),
]
BODIES = {
    "p1": text_to_doc("Intro"),
    "p2": text_to_doc("Other intro"),
    "p3": _doc({"type": "paragraph"}, {"type": "heading", "attrs": {"level": 2}}),
    "p4": _doc({"type": "image", "attrs": {"src": "/api/files/x/a.png"}}),
    "p5": _doc(
        _linked("guide", "/s/general/p/guide-p1slug0000"),
        _linked("gone", f"{BASE}/s/general/p/gone-missing123"),
        _linked("trashed", "/p/trashed123"),
        _linked("elsewhere", "/s/other/p/fine-fine000000"),
        _linked("site", "https://example.org/p/abc"),
        _mention("missing123", "Gone page"),
    ),
}
OUTSIDE: dict[str, dict[str, Any]] = {
    "trashed123": {"deletedAt": "2026-10-01T00:00:00Z"},
    "fine000000": {"deletedAt": None},
}


@pytest.fixture
def mock() -> Recorder:
    routes = docmost_routes()

    def recent(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        start = int(body.get("cursor") or 0)
        chunk = PAGES[start : start + 2]
        more = start + 2 < len(PAGES)
        meta = {"hasNextPage": more, "nextCursor": str(start + 2) if more else None}
        return ok({"items": chunk, "meta": meta})

    def info(request: httpx.Request) -> httpx.Response:
        page_id = json.loads(request.content)["pageId"]
        if page_id in BODIES:
            page = next(page for page in PAGES if page["id"] == page_id)
            return ok({**page, "content": BODIES[page_id]})
        if page_id in OUTSIDE:
            return ok({"id": page_id, "slugId": page_id, "spaceId": "s3", **OUTSIDE[page_id]})
        return error(404, "Page not found")

    def space(request: httpx.Request) -> httpx.Response:
        space_id = json.loads(request.content)["spaceId"]
        return ok(GENERAL if space_id == "s1" else SECRET)

    members = [{"id": "u1", "name": "Anna"}, {"id": "u2", "name": "Boris"}]
    routes.update(
        {
            "/api/pages/recent": recent,
            "/api/pages/info": info,
            "/api/spaces/info": space,
            "/api/spaces": ok({"items": [GENERAL, SECRET], "meta": {"hasNextPage": False}}),
            "/api/workspace/members": ok({"items": members, "meta": {"hasNextPage": False}}),
        }
    )
    return Recorder(routes)


@pytest.fixture
def server(engine: AsyncEngine, mock: Recorder) -> Iterator[RunningServer]:
    with RunningServer(mock.client()) as running:
        yield running


def test_is_empty() -> None:
    assert is_empty(BODIES["p3"])
    assert is_empty(_doc())
    assert not is_empty(BODIES["p1"])
    assert not is_empty(BODIES["p4"])


def test_page_links() -> None:
    assert page_links(BODIES["p5"], BASE) == [
        ("p1slug0000", "/s/general/p/guide-p1slug0000"),
        ("missing123", "/s/general/p/gone-missing123"),
        ("trashed123", "/p/trashed123"),
        ("fine000000", "/s/other/p/fine-fine000000"),
        ("missing123", "@Gone page"),
    ]


def test_check_space_health(server: RunningServer) -> None:
    data = server.call(server.token(), "check_space_health", {"space_id": "s1"})
    assert data["pages_checked"] == 5
    assert data["truncated"] is False
    assert data["summary"] == {
        "stale": 1,
        "empty": 1,
        "untitled": 1,
        "duplicate_titles": 1,
        "broken_links": 3,
    }
    assert [page["id"] for page in data["stale"]] == ["p4"]
    assert data["stale"][0]["url"] == f"{BASE}/s/general/p/p4slug0000"
    assert [page["id"] for page in data["empty"]] == ["p3"]
    assert [page["title"] for page in data["untitled"]] == ["(untitled)"]
    assert [page["id"] for page in data["duplicate_titles"][0]["pages"]] == ["p1", "p2"]
    assert [(item["link"], item["problem"]) for item in data["broken_links"]] == [
        ("/s/general/p/gone-missing123", "page not found or not accessible"),
        ("/p/trashed123", "page is in Trash"),
        ("@Gone page", "page not found or not accessible"),
    ]
    assert data["top_editors"] == [
        {"id": "u1", "name": "Anna", "pages": 3},
        {"id": "u2", "name": "Boris", "pages": 2},
    ]


def test_stale_days_and_max_pages(server: RunningServer) -> None:
    data = server.call(
        server.token(), "check_space_health", {"space_id": "s1", "stale_days": 2, "max_pages": 3}
    )
    assert data["pages_checked"] == 3
    assert data["truncated"] is True
    assert [page["id"] for page in data["stale"]] == ["p3", "p2"]


def test_space_restriction(engine: AsyncEngine, mock: Recorder) -> None:
    with RunningServer(mock.client(), allowed_spaces="general") as restricted:
        token = restricted.token()
        with pytest.raises(ToolError, match="Space not found"):
            restricted.call(token, "check_space_health", {"space_id": "s2"})
