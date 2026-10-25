"""Read tools end to end: MCP client → this server → real Docmost."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, MEMBER, OWNER

pytestmark = pytest.mark.integration


def _owner_call(tokens: dict[str, str], path: str, body: dict[str, Any]) -> Any:
    response = httpx.post(
        f"{DOCMOST_URL}/api/{path}",
        json=body,
        headers={"authorization": f"Bearer {tokens[OWNER[0]]}"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("data")


@pytest.fixture
def server(engine: AsyncEngine, tokens: dict[str, str]) -> Iterator[RunningServer]:
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as running:
        yield running


def test_read_tools(server: RunningServer, tokens: dict[str, str]) -> None:
    unique = uuid.uuid4().hex[:10]
    spaces = _owner_call(tokens, "spaces", {})["items"]
    general = next(space["id"] for space in spaces if space["slug"] == "general")
    parent = _owner_call(
        tokens,
        "pages/create",
        {
            "spaceId": general,
            "title": f"Guide {unique}",
            "content": f"intro{unique}",
            "format": "markdown",
        },
    )
    child = _owner_call(
        tokens,
        "pages/create",
        {
            "spaceId": general,
            "parentPageId": parent["id"],
            "title": "Child",
            "content": "# Child\n\nBody",
            "format": "markdown",
        },
    )
    private = _owner_call(tokens, "spaces/create", {"name": f"P {unique}", "slug": f"p{unique}"})
    hidden = _owner_call(tokens, "pages/create", {"spaceId": private["id"], "title": "Hidden"})

    token = server.token(email=MEMBER[0], password=MEMBER[1])

    listed = server.call(token, "list_spaces")
    assert general in {space["id"] for space in listed["spaces"]}
    assert private["id"] not in {space["id"] for space in listed["spaces"]}

    children = server.call(
        token, "list_pages", {"space_id": general, "parent_page_id": parent["id"]}
    )
    assert [page["id"] for page in children["pages"]] == [child["id"]]

    page = server.call(token, "get_page", {"page": child["slugId"]})
    assert page["id"] == child["id"]
    assert page["path"] == [f"Guide {unique}"]
    assert "# Child" in page["content"]

    hits = server.call(token, "search", {"query": f"intro{unique}"})
    assert [hit["id"] for hit in hits["results"]] == [parent["id"]]

    with pytest.raises(ToolError, match="not found"):
        server.call(token, "get_page", {"page": hidden["id"]})
