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

GENERAL = {"id": "s1", "name": "General", "slug": "general", "membership": {"role": "admin"}}
SECRET = {"id": "s2", "name": "Secret", "slug": "secret", "membership": {"role": "admin"}}
GROUP_ID = "0b2c4d6e-0000-4000-8000-000000000001"
DONE = httpx.Response(200, json={"success": True, "status": 200})


def _routes() -> dict[str, Handler | httpx.Response]:
    routes = docmost_routes()

    def space(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return ok(
            {
                "id": body.get("spaceId", "s9"),
                "name": body.get("name", "General"),
                "slug": body.get("slug", "general"),
                "description": body.get("description", ""),
                "memberCount": 1,
            }
        )

    def people(request: httpx.Request) -> httpx.Response:
        query = str(json.loads(request.content).get("query") or "")
        items: list[dict[str, Any]] = [
            {"id": "u1", "name": "Anna", "email": "anna@example.com", "role": "owner"},
            {
                "id": "u2",
                "name": "Boris",
                "email": "Boris@example.com",
                "role": "member",
                "deactivatedAt": "2026-10-01T00:00:00Z",
            },
        ]
        items = [item for item in items if query.lower() in str(item["email"]).lower()]
        return ok({"items": items, "meta": {"hasNextPage": False}})

    def groups(request: httpx.Request) -> httpx.Response:
        query = str(json.loads(request.content).get("query") or "")
        items = [{"id": GROUP_ID, "name": "Editors", "memberCount": 3, "isDefault": False}]
        items = [item for item in items if query.lower() in str(item["name"]).lower()]
        return ok({"items": items, "meta": {"hasNextPage": False}})

    routes.update(
        {
            "/api/spaces": ok({"items": [GENERAL, SECRET], "meta": {"hasNextPage": False}}),
            "/api/spaces/create": space,
            "/api/spaces/update": space,
            "/api/spaces/members": ok(
                {
                    "items": [
                        {"id": "u1", "type": "user", "name": "Anna", "role": "admin"},
                        {
                            "id": GROUP_ID,
                            "type": "group",
                            "name": "Editors",
                            "role": "writer",
                            "memberCount": 3,
                        },
                    ],
                    "meta": {"hasNextPage": False},
                }
            ),
            "/api/spaces/members/add": DONE,
            "/api/spaces/members/change-role": DONE,
            "/api/workspace/members": people,
            "/api/groups": groups,
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


def _last(mock: Recorder, path: str) -> Any:
    return next(
        json.loads(request.content)
        for request in reversed(mock.requests)
        if request.url.path == path
    )


def test_admin_tools_need_the_admin_scope(server: RunningServer) -> None:
    tools = server.tools(server.token(scopes=("write", "delete")))
    assert "list_space_members" in tools
    assert "create_space" not in tools
    assert {"create_space", "update_space", "add_space_members"} <= set(
        server.tools(server.token(scopes=("admin",)))
    )


def test_list_members_and_groups(server: RunningServer, mock: Recorder) -> None:
    token = server.token()
    members = server.call(token, "list_space_members", {"space_id": "s1"})["members"]
    assert [item["type"] for item in members] == ["user", "group"]
    people = server.call(token, "list_workspace_members", {"query": "boris"})["members"]
    assert people == [
        {
            "id": "u2",
            "name": "Boris",
            "email": "Boris@example.com",
            "role": "member",
            "deactivated": True,
            "last_login_at": None,
        }
    ]
    assert _last(mock, "/api/workspace/members") == {"limit": 50, "cursor": None, "query": "boris"}
    assert server.call(token, "list_groups")["groups"][0]["name"] == "Editors"


def test_create_and_update_space(server: RunningServer, mock: Recorder) -> None:
    token = server.token(scopes=("admin",))
    created = server.call(token, "create_space", {"name": "Docs", "slug": "docs"})
    assert created["url"] == "https://docs.example.com/s/docs"
    assert _last(mock, "/api/spaces/create") == {"name": "Docs", "slug": "docs"}

    updated = server.call(token, "update_space", {"space_id": "s1", "description": "Wiki"})
    assert updated["description"] == "Wiki"
    assert _last(mock, "/api/spaces/update") == {"spaceId": "s1", "description": "Wiki"}
    with pytest.raises(ToolError, match="at least one"):
        server.call(token, "update_space", {"space_id": "s1"})
    with pytest.raises(ToolError):
        server.call(token, "create_space", {"name": "Bad", "slug": "with space"})


def test_add_members_by_email_and_group_name(server: RunningServer, mock: Recorder) -> None:
    token = server.token(scopes=("admin",))
    added = server.call(
        token,
        "add_space_members",
        {
            "space_id": "s1",
            "role": "reader",
            "users": ["boris@EXAMPLE.com", "u7"],
            "groups": ["editors"],
        },
    )
    assert added["user_ids"] == ["u2", "u7"]
    assert _last(mock, "/api/spaces/members/add") == {
        "spaceId": "s1",
        "role": "reader",
        "userIds": ["u2", "u7"],
        "groupIds": [GROUP_ID],
    }
    with pytest.raises(ToolError, match="No workspace member"):
        server.call(
            token, "add_space_members", {"space_id": "s1", "role": "reader", "users": ["x@y.z"]}
        )
    with pytest.raises(ToolError, match="No group"):
        server.call(
            token, "add_space_members", {"space_id": "s1", "role": "reader", "groups": ["Nope"]}
        )
    with pytest.raises(ToolError, match="at least one"):
        server.call(token, "add_space_members", {"space_id": "s1", "role": "reader"})


def test_change_role(server: RunningServer, mock: Recorder) -> None:
    token = server.token(scopes=("admin",))
    server.call(
        token, "change_space_member_role", {"space_id": "s1", "role": "writer", "group": GROUP_ID}
    )
    assert _last(mock, "/api/spaces/members/change-role") == {
        "spaceId": "s1",
        "role": "writer",
        "groupId": GROUP_ID,
    }
    with pytest.raises(ToolError, match="either user or group"):
        server.call(token, "change_space_member_role", {"space_id": "s1", "role": "writer"})


def test_allowed_spaces(restricted: RunningServer) -> None:
    token = restricted.token(scopes=("admin",))
    with pytest.raises(ToolError, match="ALLOWED_SPACES"):
        restricted.call(token, "create_space", {"name": "Docs", "slug": "docs"})
    assert (
        restricted.call(token, "create_space", {"name": "Gen", "slug": "general"})["slug"]
        == "general"
    )
    with pytest.raises(ToolError, match="ALLOWED_SPACES"):
        restricted.call(token, "update_space", {"space_id": "s1", "slug": "renamed"})
    cases: list[tuple[str, dict[str, Any]]] = [
        ("list_space_members", {"space_id": "s2"}),
        ("update_space", {"space_id": "s2", "name": "X Y"}),
        ("add_space_members", {"space_id": "s2", "role": "reader", "users": ["u1"]}),
        ("change_space_member_role", {"space_id": "s2", "role": "reader", "user": "u1"}),
    ]
    for tool, args in cases:
        with pytest.raises(ToolError, match="Space not found"):
            restricted.call(token, tool, args)
