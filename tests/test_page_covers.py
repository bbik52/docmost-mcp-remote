from __future__ import annotations

import json

import httpx
import pytest
from fastmcp.exceptions import ToolError

from tests.fakes import Recorder, docmost_routes, ok
from tests.harness import RunningServer

pytestmark = pytest.mark.usefixtures("migrated_database")


def _mock(version: str = "0.98.0", *, other_page: bool = False, image: bool = True) -> Recorder:
    page = {
        "id": "p1",
        "slugId": "slug000001",
        "spaceId": "s1",
        "coverPhoto": None,
        "coverPosition": None,
        "content": "Original body",
    }

    def update(request: httpx.Request) -> httpx.Response:
        page.update({k: v for k, v in json.loads(request.content).items() if k != "pageId"})
        return ok(page)

    routes = docmost_routes(version=version)
    routes.update(
        {
            "/api/pages/info": lambda _: ok(page),
            "/api/pages/update": update,
            "/api/files/f1/cover.png": httpx.Response(
                200, content=b"PNG", headers={"content-type": "image/png"}
            ),
            "/api/files/upload": ok(
                {"id": "cover1", "fileName": "cover.png", "pageId": "p1", "mimeType": "image/png"}
            ),
            "/api/files/info": ok(
                {
                    "id": "f1",
                    "fileName": "cover.png",
                    "pageId": "other" if other_page else "p1",
                    "mimeType": "image/png" if image else "text/plain",
                }
            ),
        }
    )
    return Recorder(routes)


def test_cover_lifecycle_changes_metadata_only() -> None:
    mock = _mock()
    with RunningServer(mock.client()) as server:
        token = server.token(scopes=("write",))
        preset = server.call(
            token, "set_page_cover", {"page": "p1", "preset": "gradient-slate", "position": 30}
        )
        assert preset["cover"] == {"photo": "preset:gradient-slate", "position": 30}
        image = server.call(token, "set_page_cover", {"page": "p1", "attachment_id": "f1"})
        assert image["cover"]["photo"] == "/api/files/cover1/cover.png"
        assert (
            server.call(token, "set_page_cover", {"page": "p1", "remove": True})["cover"]["photo"]
            is None
        )
        writes = [json.loads(r.content) for r in mock.requests if r.url.path == "/api/pages/update"]
        assert all(
            set(body) == {"pageId", "coverPhoto", "coverPosition", "coverAttribution"}
            for body in writes
        )
        assert "set_page_cover" not in server.tools(server.token())


@pytest.mark.parametrize(
    "case",
    ["other_page", "not_image", "missing_choice", "two_choices", "external_url", "too_large"],
)
def test_invalid_cover_sources_do_not_write(case: str) -> None:
    mock = _mock(other_page=case == "other_page", image=case != "not_image")
    if case == "too_large":
        mock.routes["/api/files/f1/cover.png"] = httpx.Response(
            200, content=b"PNG", headers={"content-length": str(11 * 1024 * 1024)}
        )
    args: dict[str, object] = {"page": "p1", "attachment_id": "f1"}
    if case == "missing_choice":
        args = {"page": "p1"}
    elif case == "two_choices":
        args["remove"] = True
    elif case == "external_url":
        args = {"page": "p1", "preset": "https://example.com/a.png"}
    with RunningServer(mock.client()) as server:
        with pytest.raises(ToolError):
            server.call(server.token(scopes=("write",)), "set_page_cover", args)
        assert not any(r.url.path == "/api/pages/update" for r in mock.requests)


@pytest.mark.parametrize("version", ["0.97.0", ""])
def test_cover_requires_verified_version(version: str) -> None:
    mock = _mock(version)
    with RunningServer(mock.client()) as server:
        with pytest.raises(ToolError, match=r"0\.98\.0"):
            server.call(
                server.token(scopes=("write",)),
                "set_page_cover",
                {"page": "p1", "preset": "gradient-slate"},
            )
        assert not any(r.url.path == "/api/pages/update" for r in mock.requests)
