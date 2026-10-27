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
from fastmcp.client.elicitation import ElicitResult

from docmost_mcp_remote.docmost import DocmostClient
from docmost_mcp_remote.server import create_app
from tests.conftest import make_settings

_CSRF = re.compile(r'name="csrf" value="([^"]+)"')
_TOKEN = re.compile(r"dmr_[A-Za-z0-9_-]+")
SIGN_IN_TIMEOUT = 60.0
SIGN_IN_ATTEMPTS = 6
SIGN_IN_BACKOFF = 15.0


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class RunningServer:
    def __init__(self, docmost: DocmostClient | None = None, **settings: object) -> None:
        port = _free_port()
        self.url = f"http://127.0.0.1:{port}"
        self.public_url = f"http://localhost:{port}"
        config = make_settings(public_url=self.public_url, **settings)
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
        # Sign-in asks Docmost for its version, which Docmost checks against
        # GitHub; that can take longer than httpx's default five seconds.
        with httpx.Client(base_url=self.url, timeout=SIGN_IN_TIMEOUT) as web:
            for attempt in range(SIGN_IN_ATTEMPTS):
                csrf = _CSRF.search(web.get("/login").text)
                assert csrf
                answer = web.post(
                    "/login", data={"csrf": csrf.group(1), "email": email, "password": password}
                )
                # Docmost limits sign-ins to about ten a minute; the suite signs in more.
                if "not available right now" not in answer.text or attempt == SIGN_IN_ATTEMPTS - 1:
                    break
                time.sleep(SIGN_IN_BACKOFF)
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

    def call_asked(
        self,
        token: str,
        tool: str,
        arguments: dict[str, Any],
        *,
        answer: bool,
        asked: list[str],
        mode: Any = "auto",
    ) -> Any:
        """Call a tool from a client that can ask its person; ``answer`` is their reply.

        Each question shown is appended to ``asked``. ``mode`` "legacy" connects
        with a handshake-era protocol version, where the server asks while the
        call waits; "auto" uses the newest, where the client asks and retries.
        """

        async def reply(message: str, *_: Any) -> Any:
            asked.append(message)
            return {"confirm": True} if answer else ElicitResult(action="decline")

        async def run() -> Any:
            async with Client(
                f"{self.url}/mcp", auth=BearerAuth(token), elicitation_handler=reply, mode=mode
            ) as client:
                result = await client.call_tool(tool, arguments)
                return result.structured_content

        return asyncio.run(run())

    def tools(self, token: str) -> list[str]:
        async def run() -> list[str]:
            async with Client(f"{self.url}/mcp", auth=BearerAuth(token)) as client:
                return sorted(tool.name for tool in await client.list_tools())

        return asyncio.run(run())

    def _session(self, token: str, use: Any) -> Any:
        async def run() -> Any:
            async with Client(f"{self.url}/mcp", auth=BearerAuth(token)) as client:
                return await use(client)

        return asyncio.run(run())

    def resources(self, token: str) -> list[str]:
        """URIs of the resources and resource templates the token sees."""

        async def use(client: Client[Any]) -> list[str]:
            fixed = [str(item.uri) for item in await client.list_resources()]
            templates = [item.uri_template for item in await client.list_resource_templates()]
            return sorted(fixed + templates)

        return list(self._session(token, use))

    def read(self, token: str, uri: str) -> str:
        async def use(client: Client[Any]) -> str:
            contents = await client.read_resource(uri)
            return "".join(getattr(item, "text", "") for item in contents)

        return str(self._session(token, use))

    def prompts(self, token: str) -> list[str]:
        async def use(client: Client[Any]) -> list[str]:
            return sorted(prompt.name for prompt in await client.list_prompts())

        return list(self._session(token, use))

    def prompt(self, token: str, name: str, arguments: dict[str, Any] | None = None) -> str:
        async def use(client: Client[Any]) -> str:
            result = await client.get_prompt(name, arguments or {})
            return "".join(getattr(message.content, "text", "") for message in result.messages)

        return str(self._session(token, use))

    def complete(self, token: str, ref: Any, argument: str, value: str) -> list[str]:
        async def use(client: Client[Any]) -> list[str]:
            return list((await client.complete(ref, {"name": argument, "value": value})).values)

        return list(self._session(token, use))
