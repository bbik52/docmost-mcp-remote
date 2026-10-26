from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote import __version__
from tests.fakes import Handler, Recorder, docmost_routes, error
from tests.harness import RunningServer


@pytest.fixture
def routes() -> dict[str, Handler | httpx.Response]:
    return docmost_routes()


@pytest.fixture
def server(
    engine: AsyncEngine, routes: dict[str, Handler | httpx.Response]
) -> Iterator[RunningServer]:
    with RunningServer(Recorder(routes).client()) as running:
        yield running


def test_healthz(server: RunningServer) -> None:
    response = httpx.get(f"{server.url}/healthz")
    assert response.json() == {"status": "ok", "version": __version__}


def test_mcp_requires_token(server: RunningServer) -> None:
    for headers in ({}, {"authorization": "Bearer dmr_unknown"}, {"authorization": "Bearer x"}):
        response = httpx.post(
            f"{server.url}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"accept": "application/json, text/event-stream", **headers},
        )
        assert response.status_code == 401


def test_whoami_with_token(server: RunningServer) -> None:
    token = server.token(scopes=("write",))
    data = server.call(token, "whoami")
    assert data["email"] == "anna@example.com"
    assert data["scopes"] == ["read", "write"]
    assert data["docmost_version"] == "0.97.0"
    assert data["account_url"] == f"{server.public_url}/account"


def test_expired_docmost_session_is_reported(
    server: RunningServer, routes: dict[str, Handler | httpx.Response]
) -> None:
    token = server.token()
    routes["/api/users/me"] = error(401, "Unauthorized")
    with pytest.raises(ToolError, match=r"Sign in again at http://localhost:.*/login"):
        server.call(token, "whoami")
