from __future__ import annotations

import json

import httpx
import pytest
from fastmcp.exceptions import ToolError

from tests.fakes import Recorder, docmost_routes, ok
from tests.harness import RunningServer

pytestmark = pytest.mark.usefixtures("migrated_database")


def _mock(version: str = "0.98.0", *, ignore: bool = False) -> Recorder:
    space = {"id": "s1", "slug": "general", "name": "General", "homePageId": None}

    def update(request: httpx.Request) -> httpx.Response:
        if not ignore:
            space["homePageId"] = json.loads(request.content)["homePageId"]
        return ok(space)

    def page(request: httpx.Request) -> httpx.Response:
        page_id = json.loads(request.content)["pageId"]
        return ok(
            {
                "id": page_id,
                "slugId": "slug000001",
                "spaceId": "s2" if page_id == "other" else "s1",
                "deletedAt": "2026-11-01T00:00:00Z" if page_id == "trash" else None,
            }
        )

    routes = docmost_routes(version=version)
    routes.update(
        {
            "/api/spaces/info": lambda _: ok(space),
            "/api/pages/info": page,
            "/api/spaces/update": update,
        }
    )
    return Recorder(routes)


def test_homepage_set_reset_and_idempotence() -> None:
    mock = _mock()
    with RunningServer(mock.client()) as server:
        token = server.token(scopes=("admin",))
        assert (
            server.call(token, "set_space_homepage", {"space_id": "s1", "page": "p1"})[
                "home_page_id"
            ]
            == "p1"
        )
        assert not server.call(token, "set_space_homepage", {"space_id": "s1", "page": "p1"})[
            "changed"
        ]
        assert (
            server.call(token, "set_space_homepage", {"space_id": "s1", "page": None})[
                "home_page_id"
            ]
            is None
        )
        writes = [
            json.loads(r.content) for r in mock.requests if r.url.path == "/api/spaces/update"
        ]
        assert writes == [
            {"spaceId": "s1", "homePageId": "p1"},
            {"spaceId": "s1", "homePageId": None},
        ]
        assert "set_space_homepage" not in server.tools(server.token())


@pytest.mark.parametrize("page", ["other", "trash"])
def test_homepage_rejects_wrong_space_and_trashed_page(page: str) -> None:
    mock = _mock()
    with RunningServer(mock.client()) as server:
        with pytest.raises(ToolError, match="non-trashed page of this space"):
            server.call(
                server.token(scopes=("admin",)),
                "set_space_homepage",
                {"space_id": "s1", "page": page},
            )
        assert not any(r.url.path == "/api/spaces/update" for r in mock.requests)


@pytest.mark.parametrize("version", ["0.97.0", ""])
def test_homepage_does_not_write_when_support_unknown(version: str) -> None:
    mock = _mock(version)
    with RunningServer(mock.client()) as server:
        with pytest.raises(ToolError, match=r"0\.98\.0"):
            server.call(
                server.token(scopes=("admin",)),
                "set_space_homepage",
                {"space_id": "s1", "page": "p1"},
            )
        assert not any(r.url.path == "/api/spaces/update" for r in mock.requests)


def test_ignored_homepage_update_does_not_report_success() -> None:
    mock = _mock(ignore=True)
    with (
        RunningServer(mock.client()) as server,
        pytest.raises(ToolError, match="did not confirm"),
    ):
        server.call(
            server.token(scopes=("admin",)),
            "set_space_homepage",
            {"space_id": "s1", "page": "p1"},
        )
