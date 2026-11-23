from __future__ import annotations

import json

import httpx
import pytest
from fastmcp.exceptions import ToolError

from tests.fakes import Handler, Recorder, docmost_routes, error, ok
from tests.harness import RunningServer


def _mock(version: str = "0.98.0", *, reply: bool = False, forbidden: bool = False) -> Recorder:
    comment = {"id": "c1", "pageId": "p1", "spaceId": "s1", "resolvedAt": None}
    if reply:
        comment["parentCommentId"] = "parent"

    def resolve(request: httpx.Request) -> httpx.Response:
        if forbidden:
            return error(403, "Forbidden")
        body = json.loads(request.content)
        comment["resolvedAt"] = "2026-11-23T00:00:00Z" if body["resolved"] else None
        return ok(comment)

    routes: dict[str, Handler | httpx.Response] = docmost_routes(version=version)
    routes.update(
        {
            "/api/comments/info": lambda _: ok(comment),
            "/api/comments/resolve": resolve,
            "/api/spaces": ok({"items": [{"id": "s1", "slug": "allowed"}]}),
        }
    )
    return Recorder(routes)


def test_discussion_round_trip_and_scope(migrated_database: str) -> None:
    mock = _mock()
    with RunningServer(mock.client()) as server:
        token = server.token(scopes=("write",))
        assert server.call(token, "resolve_comment", {"comment_id": "c1"})["resolved"]
        assert not server.call(token, "reopen_comment", {"comment_id": "c1"})["resolved"]
        assert mock.body() == {"commentId": "c1", "resolved": False}
        read = server.token()
        assert "resolve_comment" not in server.tools(read)
        with pytest.raises(ToolError):
            server.call(read, "resolve_comment", {"comment_id": "c1"})


@pytest.mark.parametrize("version", ["0.97.0", ""])
def test_resolution_does_not_succeed_on_unsupported_version(
    migrated_database: str, version: str
) -> None:
    mock = _mock(version)
    with RunningServer(mock.client()) as server:
        with pytest.raises(ToolError, match=r"0\.98\.0"):
            server.call(server.token(scopes=("write",)), "resolve_comment", {"comment_id": "c1"})
        assert not any(r.url.path == "/api/comments/resolve" for r in mock.requests)


@pytest.mark.parametrize("mode", ["reply", "forbidden", "excluded"])
def test_resolution_preserves_thread_and_access_rules(migrated_database: str, mode: str) -> None:
    mock = _mock(reply=mode == "reply", forbidden=mode == "forbidden")
    with RunningServer(
        mock.client(), allowed_spaces="other" if mode == "excluded" else ""
    ) as server:
        with pytest.raises(ToolError):
            server.call(server.token(scopes=("write",)), "resolve_comment", {"comment_id": "c1"})
        if mode != "forbidden":
            assert not any(r.url.path == "/api/comments/resolve" for r in mock.requests)
