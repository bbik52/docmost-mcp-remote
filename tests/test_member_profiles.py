from __future__ import annotations

import json

import httpx
import pytest
from fastmcp.exceptions import ToolError

from tests.fakes import Recorder, docmost_routes, ok
from tests.harness import RunningServer

pytestmark = pytest.mark.usefixtures("migrated_database")


def _mock(version: str = "0.98.0") -> Recorder:
    user = {
        "id": "docmost-user-1",
        "name": "Anna",
        "email": "anna@example.com",
        "role": "member",
        "workspaceId": "w1",
        "locale": "en-US",
        "timezone": "UTC",
    }
    other = {"id": "u2", "name": "Other", "email": "other@example.com", "role": "member"}

    def update(request: httpx.Request) -> httpx.Response:
        user.update(json.loads(request.content))
        return ok(user)

    routes = docmost_routes(version=version)
    routes.update(
        {
            "/api/users/me": lambda _: ok({"user": user}),
            "/api/users/update": update,
            "/api/users/info": lambda r: ok(
                user if json.loads(r.content)["userId"] == user["id"] else other
            ),
            "/api/workspace/members": ok({"items": [user, other]}),
            "/api/spaces": ok(
                {"items": [{"id": "s1", "slug": "allowed"}, {"id": "s2", "slug": "excluded"}]}
            ),
            "/api/users/recent-pages": ok(
                {
                    "items": [
                        {
                            "id": "p1",
                            "slugId": "slug000001",
                            "title": "Visible",
                            "spaceId": "s1",
                            "activity": "edited",
                        },
                        {"id": "p2", "slugId": "slug000002", "title": "Excluded", "spaceId": "s2"},
                    ],
                    "meta": {"hasNextPage": True, "nextCursor": "pages-next"},
                }
            ),
            "/api/users/spaces": ok(
                {
                    "items": [{"id": "s1", "slug": "allowed"}, {"id": "s2", "slug": "excluded"}],
                    "meta": {"hasNextPage": True, "nextCursor": "spaces-next"},
                }
            ),
        }
    )
    return Recorder(routes)


def test_profile_filters_activity_and_keeps_pagination() -> None:
    mock = _mock()
    with RunningServer(mock.client(), allowed_spaces="allowed") as server:
        result = server.call(
            server.token(),
            "get_member_profile",
            {"pages_cursor": "before", "spaces_cursor": "s-before"},
        )
        assert result["profile"]["locale"] == "en-US"
        assert [p["id"] for p in result["recent_pages"]["pages"]] == ["p1"]
        assert [s["id"] for s in result["spaces"]["spaces"]] == ["s1"]
        assert result["recent_pages"]["next_cursor"] == "pages-next"
        assert result["spaces"]["next_cursor"] == "spaces-next"
        requests = {r.url.path: json.loads(r.content) for r in mock.requests if r.content}
        assert requests["/api/users/recent-pages"]["cursor"] == "before"
        assert requests["/api/users/spaces"]["cursor"] == "s-before"
        other = server.call(server.token(), "get_member_profile", {"user": "other@example.com"})
        assert other["profile"]["id"] == "u2"
        assert "timezone" not in other["profile"]


def test_self_profile_updates_safe_fields_only() -> None:
    mock = _mock()
    with RunningServer(mock.client()) as server:
        token = server.token(scopes=("write",))
        result = server.call(
            token,
            "update_my_profile",
            {"name": "New name", "locale": "ru-RU", "timezone": "Europe/Moscow"},
        )
        assert result["name"] == "New name"
        assert result["timezone"] == "Europe/Moscow"
        write = next(
            json.loads(r.content) for r in mock.requests if r.url.path == "/api/users/update"
        )
        assert set(write) == {"name", "locale", "timezone"}
        assert "update_my_profile" not in server.tools(server.token())
        with pytest.raises(ToolError):
            server.call(token, "update_my_profile", {"user_id": "u2", "name": "Bad change"})


@pytest.mark.parametrize(
    "args", [{}, {"name": "   "}, {"timezone": "not/a-zone"}, {"locale": "made-up"}]
)
def test_invalid_profile_changes_do_not_write(args: dict[str, object]) -> None:
    mock = _mock()
    with RunningServer(mock.client()) as server:
        with pytest.raises(ToolError):
            server.call(server.token(scopes=("write",)), "update_my_profile", args)
        assert not any(r.url.path == "/api/users/update" for r in mock.requests)


@pytest.mark.parametrize("version", ["0.97.0", ""])
def test_profile_writes_require_verified_support(version: str) -> None:
    mock = _mock(version)
    with RunningServer(mock.client()) as server:
        with pytest.raises(ToolError, match=r"0\.98\.0"):
            server.call(server.token(scopes=("write",)), "update_my_profile", {"name": "No write"})
        assert not any(r.url.path == "/api/users/update" for r in mock.requests)
