from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.fakes import Recorder, ok
from tests.harness import RunningServer
from tests.test_manage_tools import DONE, GROUP_ID, _last, _routes

INVITE_ID = "0b2c4d6e-0000-4000-8000-0000000000aa"


@pytest.fixture
def mock() -> Recorder:
    routes = _routes()

    def invites(request: httpx.Request) -> httpx.Response:
        query = str(json.loads(request.content).get("query") or "")
        items = [{"id": INVITE_ID, "email": "pending@example.com", "role": "member"}]
        items = [item for item in items if query.lower() in item["email"]]
        return ok({"items": items, "meta": {"hasNextPage": False}})

    def group(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return ok({"id": body.get("groupId", GROUP_ID), "name": body.get("name", "Editors")})

    routes.update(
        {
            "/api/groups/members": ok(
                {
                    "items": [{"id": "u1", "name": "Anna", "email": "anna@example.com"}],
                    "meta": {"hasNextPage": False},
                }
            ),
            "/api/groups/create": group,
            "/api/groups/update": group,
            "/api/groups/members/add": DONE,
            "/api/workspace/invites": invites,
            "/api/workspace/invites/create": DONE,
            "/api/workspace/invites/resend": DONE,
            "/api/workspace/invites/revoke": DONE,
            "/api/workspace/members/change-role": DONE,
            "/api/workspace/members/activate": DONE,
            "/api/workspace/members/deactivate": DONE,
        }
    )
    return Recorder(routes)


@pytest.fixture
def server(engine: AsyncEngine, mock: Recorder) -> Iterator[RunningServer]:
    with RunningServer(mock.client()) as running:
        yield running


def test_changes_need_the_admin_scope(server: RunningServer) -> None:
    tools = set(server.tools(server.token(scopes=("write", "delete"))))
    assert {"list_group_members", "list_invitations"} <= tools
    assert not {"invite_people", "create_group", "deactivate_member"} & tools
    admin = set(server.tools(server.token(scopes=("admin",))))
    assert {"invite_people", "change_workspace_role", "deactivate_member"} <= admin
    assert not {"remove_group_member", "delete_group", "remove_member"} & admin


def test_groups(server: RunningServer, mock: Recorder) -> None:
    listed = server.call(server.token(), "list_group_members", {"group": "editors"})
    assert listed["group_id"] == GROUP_ID
    assert [item["email"] for item in listed["members"]] == ["anna@example.com"]

    token = server.token(scopes=("admin",))
    created = server.call(token, "create_group", {"name": "Backend", "users": ["anna@example.com"]})
    assert created["name"] == "Backend"
    assert _last(mock, "/api/groups/create") == {"name": "Backend", "userIds": ["u1"]}

    server.call(token, "update_group", {"group": GROUP_ID, "description": "Edits"})
    assert _last(mock, "/api/groups/update") == {"groupId": GROUP_ID, "description": "Edits"}
    with pytest.raises(ToolError, match="Give name or description"):
        server.call(token, "update_group", {"group": GROUP_ID})

    added = server.call(token, "add_group_members", {"group": "Editors", "users": ["u2"]})
    assert added == {"group_id": GROUP_ID, "added_user_ids": ["u2"]}
    with pytest.raises(ToolError, match="No group is named 'Nope'"):
        server.call(token, "add_group_members", {"group": "Nope", "users": ["u2"]})


def test_invite_skips_members_and_pending(server: RunningServer, mock: Recorder) -> None:
    token = server.token(scopes=("admin",))
    data = server.call(
        token,
        "invite_people",
        {
            "emails": ["New@example.com", "anna@example.com", "pending@example.com"],
            "groups": ["Editors"],
        },
    )
    assert data == {
        "invited": ["new@example.com"],
        "role": "member",
        "group_ids": [GROUP_ID],
        "already_members": ["anna@example.com"],
        "already_invited": ["pending@example.com"],
    }
    assert _last(mock, "/api/workspace/invites/create") == {
        "emails": ["new@example.com"],
        "role": "member",
        "groupIds": [GROUP_ID],
    }
    with pytest.raises(ToolError):
        server.call(token, "invite_people", {"emails": ["not-an-email"]})
    with pytest.raises(ToolError):
        server.call(token, "invite_people", {"emails": ["x@example.com"], "role": "owner"})


def test_invitations(server: RunningServer, mock: Recorder) -> None:
    listed = server.call(server.token(), "list_invitations")["invitations"]
    assert [item["email"] for item in listed] == ["pending@example.com"]
    token = server.token(scopes=("admin",))
    server.call(token, "resend_invitation", {"invitation_id": INVITE_ID})
    assert _last(mock, "/api/workspace/invites/resend") == {"invitationId": INVITE_ID}
    server.call(token, "revoke_invitation", {"invitation_id": INVITE_ID})
    assert _last(mock, "/api/workspace/invites/revoke") == {"invitationId": INVITE_ID}


def test_workspace_role_and_deactivation(server: RunningServer, mock: Recorder) -> None:
    token = server.token(scopes=("admin",))
    server.call(token, "change_workspace_role", {"user": "boris@example.com", "role": "admin"})
    assert _last(mock, "/api/workspace/members/change-role") == {"userId": "u2", "role": "admin"}
    assert server.call(token, "deactivate_member", {"user": "u2"})["deactivated"] is True
    assert _last(mock, "/api/workspace/members/deactivate") == {"userId": "u2"}
    assert server.call(token, "activate_member", {"user": "u2"})["deactivated"] is False
    assert _last(mock, "/api/workspace/members/activate") == {"userId": "u2"}


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_risky_changes_ask_the_person(server: RunningServer, mock: Recorder, mode: str) -> None:
    token = server.token(scopes=("admin",))
    asked: list[str] = []
    args = {"user": "boris@example.com"}
    data = server.call_asked(token, "deactivate_member", args, answer=True, asked=asked, mode=mode)
    assert data["deactivated"] is True
    assert asked == [
        "Deactivate boris@example.com in Docmost? They are signed out and cannot sign in "
        "until they are activated again."
    ]
    sent = [r for r in mock.requests if r.url.path == "/api/workspace/members/deactivate"]
    assert len(sent) == 1

    with pytest.raises(ToolError, match="the person declined"):
        server.call_asked(
            token,
            "invite_people",
            {"emails": ["new@example.com"]},
            answer=False,
            asked=asked,
            mode=mode,
        )
    assert asked[-1].startswith("Invite new@example.com to the Docmost workspace as member?")
    assert not [r for r in mock.requests if r.url.path == "/api/workspace/invites/create"]


def test_nothing_to_ask_when_everyone_is_invited(server: RunningServer) -> None:
    token = server.token(scopes=("admin",))
    asked: list[str] = []
    data = server.call_asked(
        token, "invite_people", {"emails": ["anna@example.com"]}, answer=False, asked=asked
    )
    assert data["already_members"] == ["anna@example.com"]
    assert asked == []
