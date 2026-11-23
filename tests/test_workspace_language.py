from __future__ import annotations

import json

import httpx
import pytest
from fastmcp.exceptions import ToolError

from docmost_mcp_remote.tools import manage
from tests.fakes import Recorder, docmost_routes, error, ok
from tests.harness import RunningServer

pytestmark = pytest.mark.usefixtures("migrated_database")


def _mock(version: str = "0.98.0", *, forbidden: bool = False, ignore: bool = False) -> Recorder:
    settings = {"defaultLocale": "en-US", "unrelated": "keep"}
    user = {"id": "u1", "name": "Owner", "email": "owner@example.com", "workspaceId": "w1"}

    def update(request: httpx.Request) -> httpx.Response:
        if forbidden:
            return error(403, "Forbidden")
        if not ignore:
            settings["defaultLocale"] = json.loads(request.content)["defaultLocale"]
        return ok({"settings": settings})

    routes = docmost_routes(version=version)
    routes.update(
        {
            "/api/users/me": lambda _: ok(
                {"user": user, "workspace": {"settings": settings, "licenseKey": "do-not-return"}}
            ),
            "/api/workspace/update": update,
        }
    )
    return Recorder(routes)


def test_workspace_language_whitelisted_and_idempotent() -> None:
    mock = _mock()
    with RunningServer(mock.client()) as server:
        token = server.token(scopes=("admin",))
        assert server.call(token, "get_workspace_language") == {"default_locale": "en-US"}
        changed = server.call(token, "set_workspace_language", {"locale": "ru-RU"})
        assert changed["default_locale"] == "ru-RU"
        assert changed["previous_locale"] == "en-US"
        assert not server.call(token, "set_workspace_language", {"locale": "ru-RU"})["changed"]
        writes = [
            json.loads(r.content) for r in mock.requests if r.url.path == "/api/workspace/update"
        ]
        assert writes == [{"defaultLocale": "ru-RU"}]
        read = server.token()
        assert "set_workspace_language" not in server.tools(read)
        assert "get_workspace_language" not in server.tools(read)


@pytest.mark.parametrize("version", ["0.97.0", ""])
def test_language_requires_verified_support(version: str) -> None:
    mock = _mock(version)
    with RunningServer(mock.client()) as server:
        with pytest.raises(ToolError, match=r"0\.98\.0"):
            server.call(
                server.token(scopes=("admin",)), "set_workspace_language", {"locale": "ru-RU"}
            )
        assert not any(r.url.path == "/api/workspace/update" for r in mock.requests)


@pytest.mark.parametrize("mode", ["forbidden", "ignored", "declined", "invalid"])
def test_language_does_not_bypass_backend_or_confirmation(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock = _mock(forbidden=mode == "forbidden", ignore=mode == "ignored")
    if mode == "declined":

        async def decline(_: object) -> str:
            raise ToolError("The person declined")

        monkeypatch.setattr(manage, "confirm", decline)
    with RunningServer(mock.client()) as server:
        with pytest.raises(ToolError):
            server.call(
                server.token(scopes=("admin",)),
                "set_workspace_language",
                {"locale": "fake" if mode == "invalid" else "ru-RU"},
            )
        if mode in {"invalid", "declined"}:
            assert not any(r.url.path == "/api/workspace/update" for r in mock.requests)
