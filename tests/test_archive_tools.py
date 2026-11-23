"""Archive queries must preserve member permissions and the administrator's allowlist."""

from __future__ import annotations

import json

import httpx
import pytest
from fastmcp.exceptions import ToolError

from tests.fakes import Handler, Recorder, docmost_routes, ok
from tests.harness import RunningServer

ARCHIVE = {
    "id": "sa",
    "name": "Archive",
    "slug": "allowed",
    "archivedAt": "2026-11-21T00:00:00Z",
    "membership": {"role": "admin"},
}
OTHER = {"id": "sb", "name": "Other", "slug": "other"}


def _routes(version: str = "0.98.0") -> dict[str, Handler | httpx.Response]:
    routes = docmost_routes(version=version)

    def spaces(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("status") == "archived" or body.get("cursor") == "next":
            return ok({"items": [ARCHIVE], "meta": {"hasNextPage": False}})
        if body.get("status") == "all":
            return ok({"items": [OTHER], "meta": {"hasNextPage": True, "nextCursor": "next"}})
        return ok({"items": [OTHER], "meta": {"hasNextPage": False}})

    routes.update(
        {
            "/api/spaces": spaces,
            "/api/spaces/info": ok(ARCHIVE),
            "/api/search": ok(
                {
                    "items": [
                        {"id": "p1", "slugId": "slug000001", "spaceId": "sa", "space": ARCHIVE},
                        {"id": "p2", "slugId": "slug000002", "spaceId": "sb", "space": OTHER},
                    ]
                }
            ),
        }
    )
    return routes


def test_archive_scope_resolution_paginates(migrated_database: str) -> None:
    mock = Recorder(_routes())
    with RunningServer(mock.client(), allowed_spaces="allowed") as server:
        token = server.token()
        assert server.call(token, "list_spaces")["spaces"] == []
        space = server.call(token, "get_space", {"space_id": "sa"})
        assert space["archived"] is True
        result = server.call(token, "search", {"query": "x", "include_archived": True})
        assert [hit["id"] for hit in result["results"]] == ["p1"]
        assert result["results"][0]["archived"] is True
        bodies = [json.loads(r.content) for r in mock.requests if r.url.path == "/api/spaces"]
        assert any(b.get("status") == "all" and b.get("cursor") == "next" for b in bodies)
        assert mock.body()["includeArchived"] is True
        found = server.call(token, "list_spaces", {"status": "archived"})
        assert [space["id"] for space in found["spaces"]] == ["sa"]


def test_archive_query_does_not_bypass_allowlist(migrated_database: str) -> None:
    mock = Recorder(_routes())
    with RunningServer(mock.client(), allowed_spaces="other") as server:
        with pytest.raises(ToolError, match="Space not found"):
            server.call(server.token(), "get_space", {"space_id": "sa"})
        assert not any(r.url.path == "/api/spaces/info" for r in mock.requests)


@pytest.mark.parametrize("version", ["0.97.0", ""])
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("search", {"query": "x", "include_archived": True}),
        ("list_spaces", {"status": "archived"}),
    ],
)
def test_archive_filters_require_verified_support(
    migrated_database: str, version: str, tool: str, args: dict[str, object]
) -> None:
    mock = Recorder(_routes(version))
    with RunningServer(mock.client()) as server:
        with pytest.raises(ToolError, match=r"0\.98\.0"):
            server.call(server.token(), tool, args)
        assert not any(r.url.path == "/api/search" for r in mock.requests)
