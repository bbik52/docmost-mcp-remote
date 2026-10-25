"""Runs the real server in a background thread for end-to-end tests."""

from __future__ import annotations

import asyncio
import re
import socket
import threading
import time
from typing import Any

import httpx
import uvicorn
from fastmcp import Client
from fastmcp.client.auth import BearerAuth

from docmost_mcp_remote.docmost import DocmostClient
from docmost_mcp_remote.server import create_app
from tests.conftest import make_settings

_CSRF = re.compile(r'name="csrf" value="([^"]+)"')
_TOKEN = re.compile(r"dmr_[A-Za-z0-9_-]+")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class RunningServer:
    def __init__(self, docmost: DocmostClient | None = None, **settings: object) -> None:
        port = _free_port()
        self.url = f"http://127.0.0.1:{port}"
        config = make_settings(public_url=f"http://localhost:{port}", **settings)
        app = create_app(config, docmost)
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> RunningServer:
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("server did not start")

    def __exit__(self, *_: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)

    def token(
        self,
        scopes: tuple[str, ...] = (),
        email: str = "anna@example.com",
        password: str = "pw",
    ) -> str:
        """Sign in through the web form and create a personal token."""
        with httpx.Client(base_url=self.url) as web:
            csrf = _CSRF.search(web.get("/login").text)
            assert csrf
            web.post("/login", data={"csrf": csrf.group(1), "email": email, "password": password})
            csrf = _CSRF.search(web.get("/account").text)
            assert csrf, "sign-in failed"
            created = web.post(
                "/account/tokens",
                data={"csrf": csrf.group(1), "name": "test", "scope": list(scopes)},
            ).text
        token = _TOKEN.search(created)
        assert token
        return token.group(0)

    def call(self, token: str, tool: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call one tool and return its structured result."""

        async def run() -> Any:
            async with Client(f"{self.url}/mcp", auth=BearerAuth(token)) as client:
                result = await client.call_tool(tool, arguments or {})
                return result.structured_content

        return asyncio.run(run())

    def tools(self, token: str) -> list[str]:
        async def run() -> list[str]:
            async with Client(f"{self.url}/mcp", auth=BearerAuth(token)) as client:
                return sorted(tool.name for tool in await client.list_tools())

        return asyncio.run(run())
