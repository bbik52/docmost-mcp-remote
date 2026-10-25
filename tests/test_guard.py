from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator

import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.db.engine import create_engine
from docmost_mcp_remote.tools import write
from tests.conftest import DATABASE_TEST_URL
from tests.harness import RunningServer
from tests.test_write_tools import FakeDocmost

SECRET_TEXT = "body-text-that-must-not-be-logged"


@pytest.fixture(autouse=True)
def fast_read_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(write, "READ_BACK_DELAYS", (0.01, 0.01))


@pytest.fixture
def docmost() -> FakeDocmost:
    return FakeDocmost()


@pytest.fixture
def server(engine: AsyncEngine, docmost: FakeDocmost) -> Iterator[RunningServer]:
    with RunningServer(docmost.recorder.client(), tool_calls_per_minute=5) as running:
        yield running


def _query(sql: str) -> list[tuple[object, ...]]:
    """Run a query on a fresh engine: the tools run on another event loop."""

    async def run() -> list[tuple[object, ...]]:
        engine = create_engine(DATABASE_TEST_URL)
        try:
            async with engine.connect() as connection:
                return [tuple(row) for row in await connection.execute(text(sql))]
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _audit() -> list[tuple[object, ...]]:
    return _query("SELECT tool, page_id, space_id, outcome FROM audit_log ORDER BY id")


def test_audit_log(server: RunningServer) -> None:
    token = server.token(scopes=("write",))
    server.call(token, "update_page", {"page": "p1", "content": SECRET_TEXT})
    server.call(token, "list_pages", {"space_id": "s1"})
    with pytest.raises(ToolError):
        server.call(token, "get_page", {"page": "missing"})
    assert _audit() == [
        ("update_page", "p1", None, "ok"),
        ("list_pages", None, "s1", "ok"),
        ("get_page", "missing", None, "error"),
    ]
    assert SECRET_TEXT not in str(_query("SELECT * FROM audit_log"))


def test_rate_limit_per_member(server: RunningServer) -> None:
    first, second = server.token(), server.token()
    for token in (first, second, first, second, first):
        server.call(token, "whoami")
    # The limit counts the member, not the token.
    with pytest.raises(ToolError, match="Too many tool calls"):
        server.call(second, "whoami")
    assert _audit()[-1] == ("whoami", None, None, "rate_limited")


def test_logs_hold_no_secrets(
    server: RunningServer, docmost: FakeDocmost, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    token = server.token(scopes=("write",), password="pw")
    server.call(token, "update_page", {"page": "p1", "content": SECRET_TEXT})
    server.call(token, "get_page", {"page": "p1"})
    # The test's own MCP client logs what it sends; only the server side counts.
    logged = "\n".join(
        record.getMessage()
        for record in caplog.records
        if not record.name.startswith(("mcp.client", "fastmcp.client"))
    )
    assert "Member" in logged  # the capture works
    for secret in (token, "docmost-token", SECRET_TEXT, "# Guide", "anna@example.com"):
        assert secret not in logged, secret
