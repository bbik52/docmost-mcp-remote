"""Groups, invitations and workspace roles against real Docmost."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import httpx
import pytest

from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, OWNER

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def server(migrated_database: str, tokens: dict[str, str]) -> Iterator[RunningServer]:
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as running:
        yield running


def _accept(owner_token: str, invitation_id: str) -> None:
    """Join as the invited person, as the link in the invitation email does."""
    api = httpx.Client(base_url=f"{DOCMOST_URL}/api", timeout=30)
    link = api.post(
        "/workspace/invites/link",
        json={"invitationId": invitation_id},
        headers={"authorization": f"Bearer {owner_token}"},
    ).json()["data"]["inviteLink"]
    api.post(
        "/workspace/invites/accept",
        json={
            "invitationId": invitation_id,
            "token": link.split("token=", 1)[1],
            "name": "Newcomer",
            "password": "Newcomer-password-1",
        },
    ).raise_for_status()


def test_people(server: RunningServer, tokens: dict[str, str]) -> None:
    token = server.token(scopes=("admin",), email=OWNER[0], password=OWNER[1])
    unique = uuid.uuid4().hex[:8]
    email = f"new-{unique}@example.com"
    group = server.call(token, "create_group", {"name": f"Team {unique}"})

    invited = server.call(token, "invite_people", {"emails": [email], "groups": [group["id"]]})
    assert invited["invited"] == [email]
    again = server.call(token, "invite_people", {"emails": [email, OWNER[0]]})
    assert again["already_invited"] == [email]
    assert again["already_members"] == [OWNER[0]]

    pending = server.call(token, "list_invitations", {"query": unique})["invitations"]
    assert [item["email"] for item in pending] == [email]
    server.call(token, "resend_invitation", {"invitation_id": pending[0]["id"]})
    _accept(tokens[OWNER[0]], pending[0]["id"])

    members = server.call(token, "list_group_members", {"group": group["id"]})["members"]
    assert [item["email"] for item in members] == [email]

    server.call(token, "change_workspace_role", {"user": email, "role": "admin"})
    people = server.call(token, "list_workspace_members", {"query": email})["members"]
    assert people[0]["role"] == "admin"

    server.call(token, "deactivate_member", {"user": email})
    people = server.call(token, "list_workspace_members", {"query": email})["members"]
    assert people[0]["deactivated"] is True
    server.call(token, "activate_member", {"user": email})
    people = server.call(token, "list_workspace_members", {"query": email})["members"]
    assert people[0]["deactivated"] is False

    other = f"later-{unique}@example.com"
    server.call(token, "invite_people", {"emails": [other]})
    invitation = server.call(token, "list_invitations", {"query": other})["invitations"][0]
    server.call(token, "revoke_invitation", {"invitation_id": invitation["id"]})
    assert server.call(token, "list_invitations", {"query": other})["invitations"] == []
