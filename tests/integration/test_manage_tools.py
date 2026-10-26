"""Space management against real Docmost, as the workspace owner."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, MEMBER, OWNER

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def server(migrated_database: str, tokens: dict[str, str]) -> Iterator[RunningServer]:
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as running:
        yield running


def test_manage_space(server: RunningServer) -> None:
    token = server.token(scopes=("admin",), email=OWNER[0], password=OWNER[1])
    slug = f"s{uuid.uuid4().hex[:10]}"

    space = server.call(token, "create_space", {"name": "Managed", "slug": slug})
    assert space["slug"] == slug
    updated = server.call(
        token, "update_space", {"space_id": space["id"], "description": "Made by the tests"}
    )
    assert updated["description"] == "Made by the tests"

    people = server.call(token, "list_workspace_members", {"query": "member@"})["members"]
    assert [person["email"] for person in people] == [MEMBER[0]]

    server.call(
        token,
        "add_space_members",
        {"space_id": space["id"], "role": "reader", "users": [MEMBER[0]]},
    )
    server.call(
        token,
        "change_space_member_role",
        {"space_id": space["id"], "role": "writer", "user": MEMBER[0]},
    )
    listed = server.call(token, "list_space_members", {"space_id": space["id"]})["members"]
    roles = {item["email"]: item["role"] for item in listed if item["type"] == "user"}
    assert roles == {OWNER[0]: "admin", MEMBER[0]: "writer"}

    groups = server.call(token, "list_groups")["groups"]
    assert any(group["is_default"] for group in groups)
