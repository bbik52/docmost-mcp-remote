from __future__ import annotations

import httpx
from fastmcp import Client
from starlette.testclient import TestClient

from docmost_mcp_remote import __version__
from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.server import create_app, create_server
from tests.fakes import Recorder


def healthy() -> Recorder:
    return Recorder({"/api/health": httpx.Response(200, json={"status": "ok"})})


def test_healthz(settings: Settings) -> None:
    with TestClient(create_app(settings, healthy().client())) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_starts_when_docmost_is_down(settings: Settings) -> None:
    down = Recorder({"/api/health": httpx.Response(503)})
    with TestClient(create_app(settings, down.client())) as client:
        assert client.get("/healthz").status_code == 200
    assert down.requests[0].url.path == "/api/health"


async def test_no_tools_yet(settings: Settings) -> None:
    async with Client(create_server(settings, healthy().client())) as client:
        assert await client.list_tools() == []
