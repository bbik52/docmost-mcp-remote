from __future__ import annotations

import asyncio
import re
import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.auth import BearerAuth
from fastmcp.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote import __version__
from docmost_mcp_remote.server import create_app
from tests.conftest import make_settings
from tests.fakes import Handler, Recorder, docmost_routes, error


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class RunningServer:
    def __init__(self, routes: dict[str, Handler | httpx.Response]) -> None:
        port = _free_port()
        self.url = f"http://127.0.0.1:{port}"
        self.routes = routes
        settings = make_settings(public_url=f"http://localhost:{port}")
        app = create_app(settings, Recorder(routes).client())
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> RunningServer:
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("server did not start")

    def __exit__(self, *_: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)

    def token(self, scopes: tuple[str, ...] = ()) -> str:
        """Sign in through the web form and create a personal token."""
        with httpx.Client(base_url=self.url) as web:
            page = web.get("/login").text
            csrf = re.search(r'name="csrf" value="([^"]+)"', page)
            assert csrf
            web.post(
                "/login",
                data={"csrf": csrf.group(1), "email": "anna@example.com", "password": "pw"},
            )
            account = web.get("/account").text
            csrf = re.search(r'name="csrf" value="([^"]+)"', account)
            assert csrf
            created = web.post(
                "/account/tokens",
                data={"csrf": csrf.group(1), "name": "test", "scope": list(scopes)},
            ).text
        token = re.search(r"dmr_[A-Za-z0-9_-]+", created)
        assert token
        return token.group(0)


@pytest.fixture
def server(engine: AsyncEngine) -> Iterator[RunningServer]:
    with RunningServer(docmost_routes()) as running:
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

    async def run() -> dict[str, object]:
        async with Client(f"{server.url}/mcp", auth=BearerAuth(token)) as client:
            assert [tool.name for tool in await client.list_tools()] == ["whoami"]
            result = await client.call_tool("whoami", {})
            return dict(result.data)

    data = asyncio.run(run())
    assert data["email"] == "anna@example.com"
    assert data["scopes"] == ["read", "write"]
    assert data["docmost_version"] == "0.97.0"


def test_expired_docmost_session_is_reported(server: RunningServer) -> None:
    token = server.token()
    server.routes["/api/users/me"] = error(401, "Unauthorized")

    async def run() -> None:
        async with Client(f"{server.url}/mcp", auth=BearerAuth(token)) as client:
            await client.call_tool("whoami", {})

    with pytest.raises(ToolError, match=r"Sign in again at http://localhost:.*/login"):
        asyncio.run(run())
