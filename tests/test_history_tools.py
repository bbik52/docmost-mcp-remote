from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.harness import RunningServer
from tests.test_write_tools import FakeDocmost

V1 = str(uuid.UUID(int=1))
V2 = str(uuid.UUID(int=2))
V3 = str(uuid.UUID(int=3))


@pytest.fixture
def docmost() -> FakeDocmost:
    docmost = FakeDocmost()
    docmost.add_version(V1, "p1", "# Guide\n\nFirst draft")
    docmost.add_version(V2, "p1", "# Guide\n\nIntro")
    docmost.add_version(V3, "p3", "x")
    return docmost


@pytest.fixture
def server(engine: AsyncEngine, docmost: FakeDocmost) -> Iterator[RunningServer]:
    with RunningServer(docmost.recorder.client()) as running:
        yield running


@pytest.fixture
def token(server: RunningServer) -> str:
    return server.token(scopes=("write",))


def test_list_and_read_versions(server: RunningServer, token: str) -> None:
    listed = server.call(token, "list_page_history", {"page": "p1"})
    assert [item["id"] for item in listed["versions"]] == [V2, V1]
    assert listed["versions"][0]["last_updated_by"] == "Anna"
    assert listed["versions"][0]["contributors"] == ["Anna"]

    version = server.call(token, "get_page_version", {"version_id": V1})
    assert version["page_id"] == "p1"
    assert "First draft" in version["content"]
    assert version["content"].startswith("<docmost-untrusted-content")


def test_diff_against_current(server: RunningServer, token: str) -> None:
    data = server.call(token, "diff_page", {"page": "p1", "from_version": V1})
    assert data["changed"] is True
    assert "-First draft" in data["diff"]
    assert "+Intro" in data["diff"]

    same = server.call(token, "diff_page", {"page": "p1", "from_version": V2})
    assert same["changed"] is False

    between = server.call(token, "diff_page", {"page": "p1", "from_version": V1, "to_version": V2})
    assert "+Intro" in between["diff"]


def test_diff_against_snapshot(server: RunningServer, token: str, docmost: FakeDocmost) -> None:
    written = server.call(
        token, "update_page", {"page": "p1", "content": "Rewritten", "operation": "replace"}
    )
    data = server.call(token, "diff_page", {"page": "p1", "from_version": written["snapshot_id"]})
    assert "-Intro" in data["diff"]
    assert "+Rewritten" in data["diff"]


def test_diff_refusals(server: RunningServer, token: str) -> None:
    with pytest.raises(ToolError, match="not a version of this page"):
        server.call(token, "diff_page", {"page": "p1", "from_version": V3})
    with pytest.raises(ToolError, match="not 'current'"):
        server.call(token, "diff_page", {"page": "p1", "from_version": "yesterday"})
    with pytest.raises(ToolError, match="not found"):
        server.call(token, "diff_page", {"page": "p1", "from_version": str(uuid.uuid4())})


def test_history_respects_space_restriction(engine: AsyncEngine, docmost: FakeDocmost) -> None:
    with RunningServer(docmost.recorder.client(), allowed_spaces="general") as server:
        token = server.token()
        for tool, arguments in (
            ("list_page_history", {"page": "p3"}),
            ("get_page_version", {"version_id": V3}),
        ):
            with pytest.raises(ToolError, match="not found"):
                server.call(token, tool, arguments)
