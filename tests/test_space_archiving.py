from __future__ import annotations

import httpx
import pytest
from fastmcp.exceptions import ToolError

from docmost_mcp_remote.tools import manage
from tests.fakes import Recorder, docmost_routes, error, ok
from tests.harness import RunningServer

pytestmark = pytest.mark.usefixtures("migrated_database")


def _mock(version: str = "0.98.0", *, forbidden: bool = False) -> Recorder:
    space = {"id": "s1", "name": "Team", "slug": "team", "archivedAt": None}

    def change(archived: bool) -> httpx.Response:
        if forbidden:
            return error(403, "Forbidden")
        space["archivedAt"] = "2026-11-23T00:00:00Z" if archived else None
        return ok(space)

    routes = docmost_routes(version=version)
    routes.update(
        {
            "/api/spaces/info": lambda _: ok(space),
            "/api/spaces": lambda _: ok({"items": [space]}),
            "/api/spaces/archive": lambda _: change(True),
            "/api/spaces/unarchive": lambda _: change(False),
        }
    )
    return Recorder(routes)


def test_archive_round_trip_is_idempotent_and_admin_only() -> None:
    mock = _mock()
    with RunningServer(mock.client(), allowed_spaces="team") as server:
        token = server.token(scopes=("admin",))
        assert server.call(token, "archive_space", {"space_id": "s1"})["archived"]
        assert not server.call(token, "archive_space", {"space_id": "s1"})["changed"]
        assert not server.call(token, "unarchive_space", {"space_id": "s1"})["archived"]
        assert sum(r.url.path == "/api/spaces/archive" for r in mock.requests) == 1
        read = server.token()
        assert "archive_space" not in server.tools(read)
        with pytest.raises(ToolError):
            server.call(read, "archive_space", {"space_id": "s1"})


@pytest.mark.parametrize("version", ["0.97.0", ""])
def test_archiving_requires_known_support(version: str) -> None:
    mock = _mock(version)
    with RunningServer(mock.client()) as server:
        with pytest.raises(ToolError, match=r"0\.98\.0"):
            server.call(server.token(scopes=("admin",)), "archive_space", {"space_id": "s1"})
        assert not any(r.url.path == "/api/spaces/archive" for r in mock.requests)


@pytest.mark.parametrize("mode", ["forbidden", "excluded", "declined"])
def test_archiving_preserves_authorization_and_confirmation(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = _mock(forbidden=mode == "forbidden")
    if mode == "declined":

        async def decline(_: object) -> str:
            raise ToolError("The person declined")

        monkeypatch.setattr(manage, "confirm", decline)
    with RunningServer(
        mock.client(), allowed_spaces="other" if mode == "excluded" else ""
    ) as server:
        with pytest.raises(ToolError):
            server.call(server.token(scopes=("admin",)), "archive_space", {"space_id": "s1"})
        if mode != "forbidden":
            assert not any(r.url.path == "/api/spaces/archive" for r in mock.requests)
