from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.crypto import Cipher
from docmost_mcp_remote.db.schema import snapshots
from docmost_mcp_remote.db.snapshot_store import SnapshotStore
from docmost_mcp_remote.db.store import Store, now
from docmost_mcp_remote.tools import write
from tests.conftest import SECRET
from tests.fakes import Handler, Recorder, docmost_routes, error, ok
from tests.harness import RunningServer

SPACES = [
    {"id": "s1", "name": "General", "slug": "general"},
    {"id": "s2", "name": "Other", "slug": "other"},
]


class FakeDocmost:
    """A small stateful Docmost: pages with Markdown bodies, a tree and a Trash."""

    def __init__(self) -> None:
        self.pages: dict[str, dict[str, Any]] = {}
        self.apply_body_updates = True
        self.recorder = Recorder(self.routes())
        self.add("p1", "Guide", "# Guide\n\nIntro", position="a0VVV")
        self.add("p2", "Second", "", position="a1VVV")
        self.add("p3", "Elsewhere", "x", spaceId="s2", position="a0VVV")

    def add(self, page_id: str, title: str, content: str, **extra: Any) -> None:
        self.pages[page_id] = {
            "id": page_id,
            "slugId": f"{page_id}slug000000"[:10],
            "title": title,
            "content": content,
            "spaceId": "s1",
            "parentPageId": None,
            "position": "a0VVV",
            "deletedAt": None,
            **extra,
        }

    def requests(self, path: str) -> list[dict[str, Any]]:
        return [
            json.loads(request.content)
            for request in self.recorder.requests
            if request.url.path == f"/api/{path}"
        ]

    def routes(self) -> dict[str, Handler | httpx.Response]:
        routes = docmost_routes()

        def body(request: httpx.Request) -> dict[str, Any]:
            return dict(json.loads(request.content))

        def live(page_id: str) -> dict[str, Any] | None:
            page = self.pages.get(page_id) or next(
                (p for p in self.pages.values() if p["slugId"] == page_id), None
            )
            return page if page and page["deletedAt"] is None else None

        def info(request: httpx.Request) -> httpx.Response:
            page = live(body(request)["pageId"])
            if page is None:
                return error(404, "Page not found")
            space = next(space for space in SPACES if space["id"] == page["spaceId"])
            return ok({**page, "space": space})

        def create(request: httpx.Request) -> httpx.Response:
            data = body(request)
            page_id = f"n{len(self.pages)}"
            self.add(
                page_id,
                data["title"],
                data.get("content", ""),
                spaceId=data["spaceId"],
                parentPageId=data.get("parentPageId"),
            )
            return ok(self.pages[page_id])

        def update_page(request: httpx.Request) -> httpx.Response:
            data = body(request)
            page = live(data["pageId"])
            if page is None:
                return error(404, "Page not found")
            if "title" in data:
                page["title"] = data["title"]
            if "content" in data and self.apply_body_updates:
                text, operation = data["content"], data["operation"]
                if operation == "append":
                    page["content"] = f"{page['content']}\n\n{text}".strip()
                elif operation == "prepend":
                    page["content"] = f"{text}\n\n{page['content']}".strip()
                else:
                    page["content"] = text
            return ok(page)

        def sidebar(request: httpx.Request) -> httpx.Response:
            data = body(request)
            items = [
                page
                for page in self.pages.values()
                if page["spaceId"] == data["spaceId"]
                and page["parentPageId"] == data.get("pageId")
                and page["deletedAt"] is None
            ]
            return ok({"items": items, "meta": {"hasNextPage": False}})

        def move(request: httpx.Request) -> httpx.Response:
            data = body(request)
            page = self.pages[data["pageId"]]
            page["parentPageId"] = data["parentPageId"]
            page["position"] = data["position"]
            return httpx.Response(200, json={"success": True, "status": 200})

        def trash(request: httpx.Request) -> httpx.Response:
            page = live(body(request)["pageId"])
            if page is None:
                return error(404, "Page not found")
            page["deletedAt"] = "2026-10-25T10:00:00Z"
            return httpx.Response(200, json={"success": True, "status": 200})

        def restore(request: httpx.Request) -> httpx.Response:
            page = self.pages.get(body(request)["pageId"])
            if page is None:
                return error(404, "Page not found")
            page["deletedAt"] = None
            return ok(page)

        def trashed(request: httpx.Request) -> httpx.Response:
            items = [
                page
                for page in self.pages.values()
                if page["spaceId"] == body(request)["spaceId"] and page["deletedAt"]
            ]
            return ok({"items": items, "meta": {"hasNextPage": False}})

        def comment(request: httpx.Request) -> httpx.Response:
            data = body(request)
            return ok(
                {
                    "id": "c9",
                    "pageId": data["pageId"],
                    "parentCommentId": data.get("parentCommentId"),
                    "content": json.loads(data["content"]),
                }
            )

        routes.update(
            {
                "/api/spaces": ok({"items": SPACES, "meta": {"hasNextPage": False}}),
                "/api/pages/info": info,
                "/api/pages/breadcrumbs": ok([]),
                "/api/pages/create": create,
                "/api/pages/update": update_page,
                "/api/pages/sidebar-pages": sidebar,
                "/api/pages/move": move,
                "/api/pages/delete": trash,
                "/api/pages/restore": restore,
                "/api/pages/trash": trashed,
                "/api/comments/create": comment,
            }
        )
        return routes


@pytest.fixture(autouse=True)
def fast_read_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(write, "READ_BACK_DELAYS", (0.01, 0.01, 0.01))


@pytest.fixture
def docmost() -> FakeDocmost:
    return FakeDocmost()


@pytest.fixture
def server(engine: AsyncEngine, docmost: FakeDocmost) -> Iterator[RunningServer]:
    with RunningServer(docmost.recorder.client()) as running:
        yield running


@pytest.fixture
def token(server: RunningServer) -> str:
    return server.token(scopes=("write", "delete"))


# Scopes


def test_read_grant_cannot_write(server: RunningServer) -> None:
    read_only = server.token()
    tools = server.tools(read_only)
    for name in ("create_page", "update_page", "move_page", "add_comment", "trash_page"):
        assert name not in tools
    with pytest.raises(ToolError):
        server.call(read_only, "update_page", {"page": "p1", "content": "x"})


def test_write_grant_cannot_trash(server: RunningServer, docmost: FakeDocmost) -> None:
    writer = server.token(scopes=("write",))
    tools = server.tools(writer)
    assert "update_page" in tools
    assert "trash_page" not in tools
    assert "restore_page" not in tools
    with pytest.raises(ToolError):
        server.call(writer, "trash_page", {"page": "p1"})
    assert docmost.requests("pages/delete") == []


# Pages


def test_create_page(server: RunningServer, token: str, docmost: FakeDocmost) -> None:
    data = server.call(
        token,
        "create_page",
        {"space_id": "s1", "title": "New", "content": "Hello", "parent_page_id": "p1"},
    )
    assert data["title"] == "New"
    assert data["url"].startswith("https://docs.example.com/s/general/p/")
    assert docmost.requests("pages/create")[-1] == {
        "spaceId": "s1",
        "title": "New",
        "content": "Hello",
        "format": "markdown",
        "parentPageId": "p1",
    }


def test_create_page_parent_in_other_space(server: RunningServer, token: str) -> None:
    with pytest.raises(ToolError, match="another space"):
        server.call(token, "create_page", {"space_id": "s1", "title": "X", "parent_page_id": "p3"})


def test_create_page_body_not_saved(
    server: RunningServer, token: str, docmost: FakeDocmost
) -> None:
    original = docmost.recorder.routes["/api/pages/create"]
    assert callable(original)

    def create_without_body(request: httpx.Request) -> httpx.Response:
        response = original(request)
        page_id = response.json()["data"]["id"]
        docmost.pages[page_id]["content"] = ""
        return response

    docmost.recorder.routes["/api/pages/create"] = create_without_body
    with pytest.raises(ToolError, match="did not save its body"):
        server.call(token, "create_page", {"space_id": "s1", "title": "X", "content": "Body"})


def test_update_page_append_takes_snapshot(
    server: RunningServer, token: str, docmost: FakeDocmost
) -> None:
    data = server.call(token, "update_page", {"page": "p1", "content": "More"})
    assert data["changed"] is True
    assert docmost.pages["p1"]["content"] == "# Guide\n\nIntro\n\nMore"
    assert docmost.requests("pages/update")[-1] == {
        "pageId": "p1",
        "content": "More",
        "operation": "append",
        "format": "markdown",
    }
    listed = server.call(token, "list_snapshots", {"page": "p1"})
    assert [item["id"] for item in listed["snapshots"]] == [data["snapshot_id"]]
    assert listed["snapshots"][0]["reason"] == "update_page:append"
    assert listed["snapshots"][0]["content_chars"] == len("# Guide\n\nIntro")


def test_restore_snapshot(server: RunningServer, token: str, docmost: FakeDocmost) -> None:
    first = server.call(
        token, "update_page", {"page": "p1", "content": "Rewritten", "operation": "replace"}
    )
    assert docmost.pages["p1"]["content"] == "Rewritten"
    restored = server.call(token, "restore_snapshot", {"snapshot_id": first["snapshot_id"]})
    assert docmost.pages["p1"]["content"] == "# Guide\n\nIntro"
    assert restored["restored_snapshot_id"] == first["snapshot_id"]
    # The restore saved the rewritten body first, so it can be undone too.
    listed = server.call(token, "list_snapshots", {"page": "p1"})["snapshots"]
    assert [item["reason"] for item in listed] == ["restore_snapshot", "update_page:replace"]
    assert listed[0]["id"] == restored["snapshot_id"]


def test_unknown_snapshot(server: RunningServer, token: str) -> None:
    for snapshot_id in ("nope", str(uuid.uuid4())):
        with pytest.raises(ToolError, match="Snapshot not found"):
            server.call(token, "restore_snapshot", {"snapshot_id": snapshot_id})


def test_silent_no_op_is_reported(server: RunningServer, token: str, docmost: FakeDocmost) -> None:
    docmost.apply_body_updates = False
    with pytest.raises(ToolError, match="COLLAB_DISABLE_REDIS") as raised:
        server.call(token, "update_page", {"page": "p1", "content": "More"})
    snapshot_id = str(raised.value).rsplit("Snapshot ", 1)[1].split(" ", 1)[0]
    listed = server.call(token, "list_snapshots", {"page": "p1"})["snapshots"]
    assert [item["id"] for item in listed] == [snapshot_id]


def test_replace_with_same_body_does_not_write(
    server: RunningServer, token: str, docmost: FakeDocmost
) -> None:
    data = server.call(
        token,
        "update_page",
        {"page": "p1", "content": "# Guide\n\nIntro\n", "operation": "replace"},
    )
    assert data["changed"] is False
    assert docmost.requests("pages/update") == []


def test_snapshot_failure_blocks_the_write(
    server: RunningServer, token: str, docmost: FakeDocmost, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(self: SnapshotStore, **_: Any) -> uuid.UUID:
        raise RuntimeError("database down")

    monkeypatch.setattr(SnapshotStore, "save", broken)
    with pytest.raises(ToolError):
        server.call(token, "update_page", {"page": "p1", "content": "More"})
    assert docmost.requests("pages/update") == []


def test_space_restriction_applies_to_writes(engine: AsyncEngine, docmost: FakeDocmost) -> None:
    with RunningServer(docmost.recorder.client(), allowed_spaces="general") as server:
        token = server.token(scopes=("write", "delete"))
        for tool, arguments in (
            ("update_page", {"page": "p3", "content": "x"}),
            ("create_page", {"space_id": "s2", "title": "x"}),
            ("trash_page", {"page": "p3"}),
        ):
            with pytest.raises(ToolError, match="not found"):
                server.call(token, tool, arguments)
    assert docmost.requests("pages/update") == []
    assert docmost.requests("pages/delete") == []


def test_rename_page(server: RunningServer, token: str, docmost: FakeDocmost) -> None:
    data = server.call(token, "rename_page", {"page": "p1", "title": "Handbook"})
    assert data["title"] == "Handbook"
    assert data["previous_title"] == "Guide"
    assert docmost.requests("pages/update")[-1] == {"pageId": "p1", "title": "Handbook"}


# Moving


def test_move_page_to_end_of_parent(
    server: RunningServer, token: str, docmost: FakeDocmost
) -> None:
    docmost.add("c1", "Child", "", parentPageId="p1", position="a0VVV")
    server.call(token, "move_page", {"page": "p2", "parent_page_id": "p1"})
    moved = docmost.requests("pages/move")[-1]
    assert moved["parentPageId"] == "p1"
    assert moved["position"] > "a0VVV"
    assert 5 <= len(moved["position"]) <= 12


def test_move_page_first_and_after(server: RunningServer, token: str, docmost: FakeDocmost) -> None:
    docmost.add("p4", "Third", "", position="a2VVV")
    server.call(token, "move_page", {"page": "p4", "first": True})
    assert docmost.requests("pages/move")[-1]["position"] < "a0VVV"
    server.call(token, "move_page", {"page": "p4", "after_page_id": "p1"})
    position = docmost.requests("pages/move")[-1]["position"]
    assert "a0VVV" < position < "a1VVV"
    assert docmost.requests("pages/move")[-1]["parentPageId"] is None


def test_move_page_refusals(server: RunningServer, token: str) -> None:
    with pytest.raises(ToolError, match="within their space"):
        server.call(token, "move_page", {"page": "p1", "parent_page_id": "p3"})
    with pytest.raises(ToolError, match="its own parent"):
        server.call(token, "move_page", {"page": "p1", "parent_page_id": "p1"})
    with pytest.raises(ToolError, match="after_page_id"):
        server.call(token, "move_page", {"page": "p1", "after_page_id": "p3"})


# Comments and Trash


def test_add_comment(server: RunningServer, token: str, docmost: FakeDocmost) -> None:
    data = server.call(
        token, "add_comment", {"page": "p1", "text": "Looks good", "reply_to_comment_id": "c1"}
    )
    assert data == {"id": "c9", "page_id": "p1", "parent_comment_id": "c1"}
    sent = docmost.requests("comments/create")[-1]
    assert sent["parentCommentId"] == "c1"
    assert "Looks good" in sent["content"]


def test_trash_and_restore(server: RunningServer, token: str, docmost: FakeDocmost) -> None:
    server.call(token, "trash_page", {"page": "p1"})
    assert docmost.requests("pages/delete") == [{"pageId": "p1"}]
    trash = server.call(token, "list_trash", {"space_id": "s1"})
    assert [page["id"] for page in trash["pages"]] == ["p1"]
    restored = server.call(token, "restore_page", {"page": "p1"})
    assert restored["restored"] is True
    assert docmost.pages["p1"]["deletedAt"] is None


# Snapshot store


async def test_snapshots_are_private_and_expire(engine: AsyncEngine) -> None:
    store = Store(engine)
    anna = await store.upsert_member("u1", "anna@example.com", "Anna")
    bob = await store.upsert_member("u2", "bob@example.com", "Bob")
    snapshots_store = SnapshotStore(engine, Cipher(SECRET))
    snapshot_id = await snapshots_store.save(
        member_id=anna.id,
        page_id="p1",
        space_id="s1",
        title="Guide",
        content="secret body",
        reason="update_page:replace",
    )
    loaded = await snapshots_store.load(anna.id, snapshot_id)
    assert loaded is not None
    assert loaded.content == "secret body"
    assert await snapshots_store.load(bob.id, snapshot_id) is None
    assert await snapshots_store.list(bob.id, "p1", 10) == []

    async with engine.begin() as connection:
        raw = await connection.scalar(snapshots.select().with_only_columns(snapshots.c.ciphertext))
        assert raw is not None
        assert b"secret body" not in raw
        await connection.execute(update(snapshots).values(created_at=now() - timedelta(days=31)))
    assert await snapshots_store.cleanup(timedelta(days=30)) == 1
    assert await snapshots_store.load(anna.id, snapshot_id) is None
