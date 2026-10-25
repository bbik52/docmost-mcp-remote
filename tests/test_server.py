from __future__ import annotations

from fastmcp import Client
from starlette.testclient import TestClient

from docmost_mcp_remote import __version__
from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.server import create_app, create_server


def test_healthz(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_no_tools_without_backend(settings: Settings) -> None:
    async with Client(create_server(settings)) as client:
        assert await client.list_tools() == []
