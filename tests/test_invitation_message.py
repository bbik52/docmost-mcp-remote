from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError

from tests.fakes import Recorder, docmost_routes, ok
from tests.harness import RunningServer

pytestmark = pytest.mark.usefixtures("migrated_database")


def _mock(version: str) -> Recorder:
    routes = docmost_routes(version=version)
    routes.update(
        {
            "/api/workspace/members": ok({"items": []}),
            "/api/workspace/invites": ok({"items": []}),
            "/api/workspace/invites/create": ok(None),
        }
    )
    return Recorder(routes)


def test_invitation_message_forwarded_only_when_requested() -> None:
    mock = _mock("0.98.0")
    with RunningServer(mock.client()) as server:
        token = server.token(scopes=("admin",))
        server.call(
            token, "invite_people", {"emails": ["new@example.com"], "message": "Welcome aboard"}
        )
        body = next(
            json.loads(r.content)
            for r in mock.requests
            if r.url.path == "/api/workspace/invites/create"
        )
        assert body == {
            "emails": ["new@example.com"],
            "role": "member",
            "groupIds": [],
            "message": "Welcome aboard",
        }


def test_old_invitation_call_is_unchanged() -> None:
    mock = _mock("0.80.1")
    with RunningServer(mock.client()) as server:
        server.call(
            server.token(scopes=("admin",)), "invite_people", {"emails": ["new@example.com"]}
        )
        body = next(
            json.loads(r.content)
            for r in mock.requests
            if r.url.path == "/api/workspace/invites/create"
        )
        assert "message" not in body


@pytest.mark.parametrize("version", ["0.97.0", ""])
def test_message_requires_verified_support(version: str) -> None:
    mock = _mock(version)
    with RunningServer(mock.client()) as server:
        with pytest.raises(ToolError, match=r"0\.98\.0"):
            server.call(
                server.token(scopes=("admin",)),
                "invite_people",
                {"emails": ["new@example.com"], "message": "No silent ignore"},
            )
        assert not any(r.url.path == "/api/workspace/invites/create" for r in mock.requests)


def test_message_size_limit_and_scope() -> None:
    mock = _mock("0.98.0")
    with RunningServer(mock.client()) as server:
        with pytest.raises(ToolError):
            server.call(
                server.token(scopes=("admin",)),
                "invite_people",
                {"emails": ["new@example.com"], "message": "x" * 501},
            )
        with pytest.raises(ToolError):
            server.call(
                server.token(scopes=("write",)),
                "invite_people",
                {"emails": ["new@example.com"], "message": "No admin"},
            )
        assert not any(r.url.path == "/api/workspace/invites/create" for r in mock.requests)
