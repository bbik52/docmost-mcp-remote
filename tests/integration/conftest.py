"""Fixtures for tests against a real Docmost.

Set ``DOCMOST_TEST_URL`` (for example ``http://localhost:3000``) to run them;
``tests/integration/compose.yaml`` starts a suitable Docmost. The first run
creates the workspace and two users.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest

from docmost_mcp_remote.docmost import CeDocmostClient
from docmost_mcp_remote.docmost.ce import CeDocmostSession

DOCMOST_URL = os.environ.get("DOCMOST_TEST_URL", "")
OWNER = ("owner@example.com", "Owner-password-1")
MEMBER = ("member@example.com", "Member-password-1")

pytestmark = pytest.mark.integration


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if DOCMOST_URL:
        return
    skip = pytest.mark.skip(reason="DOCMOST_TEST_URL is not set")
    for item in items:
        if "integration" in item.nodeid.split("::")[0]:
            item.add_marker(skip)


def _bootstrap() -> dict[str, str]:
    """Create the workspace, the owner and a member, unless they exist.

    Returns session tokens by email. Docmost allows about ten sign-ins per
    minute, so tests reuse these tokens instead of signing in each time.
    """
    api = httpx.Client(base_url=f"{DOCMOST_URL}/api", timeout=30)
    api.post(
        "/auth/setup",
        json={"workspaceName": "Tests", "name": "Owner", "email": OWNER[0], "password": OWNER[1]},
    )
    owner = api.post("/auth/login", json={"email": OWNER[0], "password": OWNER[1]})
    owner.raise_for_status()
    tokens = {OWNER[0]: owner.cookies["authToken"]}
    headers = {"authorization": f"Bearer {tokens[OWNER[0]]}"}
    member = api.post("/auth/login", json={"email": MEMBER[0], "password": MEMBER[1]})
    if member.is_success:
        tokens[MEMBER[0]] = member.cookies["authToken"]
        return tokens
    api.post(
        "/workspace/invites/create",
        json={"emails": [MEMBER[0]], "role": "member", "groupIds": []},
        headers=headers,
    ).raise_for_status()
    invites = api.post("/workspace/invites", json={}, headers=headers).json()["data"]["items"]
    invite = next(item for item in invites if item["email"] == MEMBER[0])
    link = api.post(
        "/workspace/invites/link", json={"invitationId": invite["id"]}, headers=headers
    ).json()["data"]["inviteLink"]
    api.post(
        "/workspace/invites/accept",
        json={
            "invitationId": invite["id"],
            "token": link.split("token=", 1)[1],
            "name": "Member",
            "password": MEMBER[1],
        },
    ).raise_for_status()
    member = api.post("/auth/login", json={"email": MEMBER[0], "password": MEMBER[1]})
    member.raise_for_status()
    tokens[MEMBER[0]] = member.cookies["authToken"]
    return tokens


def _other_space(tokens: dict[str, str]) -> None:
    """A second space, slug ``other``, where the member is a writer."""
    api = httpx.Client(
        base_url=f"{DOCMOST_URL}/api",
        timeout=30,
        headers={"authorization": f"Bearer {tokens[OWNER[0]]}"},
    )
    spaces = api.post("/spaces", json={"limit": 100}).json()["data"]["items"]
    if any(space["slug"] == "other" for space in spaces):
        return
    space = api.post("/spaces/create", json={"name": "Other", "slug": "other"})
    space.raise_for_status()
    member = httpx.post(
        f"{DOCMOST_URL}/api/users/me",
        json={},
        headers={"authorization": f"Bearer {tokens[MEMBER[0]]}"},
        timeout=30,
    ).json()["data"]["user"]
    api.post(
        "/spaces/members/add",
        json={
            "spaceId": space.json()["data"]["id"],
            "role": "writer",
            "userIds": [member["id"]],
            "groupIds": [],
        },
    ).raise_for_status()


@pytest.fixture(scope="session")
def tokens() -> dict[str, str]:
    tokens = _bootstrap()
    _other_space(tokens)
    return tokens


@pytest.fixture
async def client(tokens: dict[str, str]) -> AsyncIterator[CeDocmostClient]:
    client = CeDocmostClient(DOCMOST_URL)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def owner(client: CeDocmostClient, tokens: dict[str, str]) -> CeDocmostSession:
    return client.session(tokens[OWNER[0]])


@pytest.fixture
def member(client: CeDocmostClient, tokens: dict[str, str]) -> CeDocmostSession:
    return client.session(tokens[MEMBER[0]])


@pytest.fixture
async def space_id(owner: CeDocmostSession) -> str:
    spaces = await owner.list_spaces()
    return next(space.id for space in spaces.items if space.slug == "general")


@pytest.fixture
def unique() -> str:
    return uuid.uuid4().hex[:10]
