from __future__ import annotations

import json

import httpx
import pytest

from docmost_mcp_remote.docmost import (
    DocmostAuthError,
    DocmostBadRequestError,
    DocmostError,
    DocmostForbiddenError,
    DocmostNotFoundError,
    DocmostResponseTooLargeError,
    DocmostUnavailableError,
    UnsupportedDocmostVersionError,
)
from docmost_mcp_remote.docmost.ce import MAX_PAGE_SIZE
from tests.fakes import Recorder, error, ok

PAGE = {
    "id": "p1",
    "slugId": "abc",
    "title": "Hello",
    "spaceId": "s1",
    "parentPageId": None,
    "content": "# Hi",
    "permissions": {"canEdit": True},
    "creator": {"id": "u1", "name": "Owner"},
}


async def test_login_returns_token_from_cookie() -> None:
    mock = Recorder(
        {"/api/auth/login": ok(None, headers={"set-cookie": "authToken=tok123; Path=/; HttpOnly"})}
    )
    client = mock.client()

    assert await client.login("a@example.com", "pw") == "tok123"
    assert mock.body() == {"email": "a@example.com", "password": "pw"}
    assert "authorization" not in mock.requests[0].headers


async def test_login_without_token_fails() -> None:
    client = Recorder({"/api/auth/login": ok(None)}).client()
    with pytest.raises(DocmostError, match="no session token"):
        await client.login("a@example.com", "pw")


async def test_login_wrong_password() -> None:
    client = Recorder({"/api/auth/login": error(401, "Email or password does not match")}).client()
    with pytest.raises(DocmostAuthError, match="does not match"):
        await client.login("a@example.com", "wrong")


async def test_session_sends_bearer_token_and_hides_it() -> None:
    mock = Recorder(
        {"/api/users/me": ok({"user": {"id": "u1", "email": "a@example.com", "workspaceId": "w1"}})}
    )
    session = mock.client().session("secret-token")

    user = await session.current_user()

    assert user.email == "a@example.com"
    assert mock.requests[0].headers["authorization"] == "Bearer secret-token"
    assert mock.requests[0].method == "POST"
    assert "secret-token" not in repr(session)


@pytest.mark.parametrize(
    ("status", "message", "exc"),
    [
        (401, "Unauthorized", DocmostAuthError),
        (403, "This feature requires a valid license.", DocmostForbiddenError),
        (404, "Page not found", DocmostNotFoundError),
        (400, ["limit must not be greater than 100"], DocmostBadRequestError),
        (422, "bad", DocmostBadRequestError),
        (429, "slow down", DocmostUnavailableError),
        (500, "boom", DocmostUnavailableError),
        (502, "bad gateway", DocmostUnavailableError),
    ],
)
async def test_error_mapping(status: int, message: str, exc: type[Exception]) -> None:
    session = Recorder({"/api/pages/info": error(status, message)}).client().session("t")
    with pytest.raises(exc):
        await session.get_page("p1")


async def test_error_message_is_docmost_text() -> None:
    session = Recorder({"/api/pages/info": error(404, "Page not found")}).client().session("t")
    with pytest.raises(DocmostNotFoundError, match=r"^Page not found$"):
        await session.get_page("p1")


async def test_non_json_answer() -> None:
    html = httpx.Response(200, text="<html></html>", headers={"content-type": "text/html"})
    session = Recorder({"/api/pages/info": html}).client().session("t")
    with pytest.raises(DocmostUnavailableError, match="non-JSON"):
        await session.get_page("p1")


async def test_timeout() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    session = Recorder({"/api/pages/info": slow}).client().session("t")
    with pytest.raises(DocmostUnavailableError, match="timed out"):
        await session.get_page("p1")


async def test_connection_error() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    session = Recorder({"/api/pages/info": down}).client().session("t")
    with pytest.raises(DocmostUnavailableError, match="not reachable"):
        await session.get_page("p1")


async def test_response_too_large_by_header() -> None:
    big = ok({**PAGE, "content": "x" * 200_000})
    session = Recorder({"/api/pages/info": big}).client(max_response_bytes=100_000).session("t")
    with pytest.raises(DocmostResponseTooLargeError):
        await session.get_page("p1")


async def test_response_too_large_when_streamed() -> None:
    body = json.dumps({"data": {**PAGE, "content": "x" * 200_000}}).encode()

    def chunked(request: httpx.Request) -> httpx.Response:
        stream = httpx.ByteStream(body)  # no content-length header
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=stream)

    session = Recorder({"/api/pages/info": chunked}).client(max_response_bytes=100_000).session("t")
    with pytest.raises(DocmostResponseTooLargeError):
        await session.get_page("p1")


async def test_get_page_asks_for_markdown() -> None:
    mock = Recorder({"/api/pages/info": ok(PAGE)})
    page = await mock.client().session("t").get_page("p1")

    assert mock.body() == {"pageId": "p1", "format": "markdown"}
    assert page.content == "# Hi"
    assert page.can_edit is True
    assert page.creator is not None
    assert page.creator.name == "Owner"


async def test_get_page_with_json_content_gives_empty_body() -> None:
    mock = Recorder({"/api/pages/info": ok({**PAGE, "content": {"type": "doc"}})})
    page = await mock.client().session("t").get_page("p1")
    assert page.content == ""


async def test_pagination_and_limit_clamp() -> None:
    data = {
        "items": [{"id": "s1", "name": "General", "membership": {"role": "admin"}}],
        "meta": {"hasNextPage": True, "nextCursor": "c2"},
    }
    mock = Recorder({"/api/spaces": ok(data)})

    result = await mock.client().session("t").list_spaces(limit=1000, cursor="c1")

    assert mock.body() == {"limit": MAX_PAGE_SIZE, "cursor": "c1"}
    assert result.has_next_page
    assert result.next_cursor == "c2"
    assert result.items[0].member_role == "admin"


async def test_list_pages_children() -> None:
    mock = Recorder({"/api/pages/sidebar-pages": ok({"items": [], "meta": {}})})
    await mock.client().session("t").list_pages("s1", parent_page_id="p1", limit=0)
    assert mock.body() == {"spaceId": "s1", "pageId": "p1", "limit": 1, "cursor": None}


async def test_search_hits() -> None:
    hit = {"id": "p1", "slugId": "a", "title": "T", "space": {"id": "s1"}, "highlight": "<b>x</b>"}
    mock = Recorder({"/api/search": ok({"items": [hit, hit, hit]})})

    hits = await mock.client().session("t").search("x", space_id="s1", limit=2)

    assert mock.body() == {"query": "x", "limit": 2, "spaceId": "s1"}
    assert len(hits) == 2
    assert hits[0].space_id == "s1"


async def test_update_body_uses_markdown_operation() -> None:
    mock = Recorder({"/api/pages/update": ok(PAGE)})
    await mock.client().session("t").update_page_body("p1", "more", "append")
    assert mock.body() == {
        "pageId": "p1",
        "content": "more",
        "operation": "append",
        "format": "markdown",
    }


async def test_create_page_with_body() -> None:
    mock = Recorder({"/api/pages/create": ok(PAGE)})
    await (
        mock.client().session("t").create_page("s1", "Hello", markdown="# Hi", parent_page_id="p0")
    )
    assert mock.body() == {
        "spaceId": "s1",
        "title": "Hello",
        "content": "# Hi",
        "format": "markdown",
        "parentPageId": "p0",
    }


async def test_move_to_trash_never_asks_for_permanent_delete() -> None:
    mock = Recorder({"/api/pages/delete": ok(None)})
    await mock.client().session("t").move_to_trash("p1")
    assert mock.body() == {"pageId": "p1"}


async def test_create_comment_sends_prosemirror_json() -> None:
    created = {
        "id": "c1",
        "pageId": "p1",
        "content": {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hi"}]}],
        },
    }
    mock = Recorder({"/api/comments/create": ok(created)})

    comment = await mock.client().session("t").create_comment("p1", "Hi", parent_comment_id="c0")

    body = mock.body()
    assert body["parentCommentId"] == "c0"
    assert json.loads(body["content"])["type"] == "doc"
    assert comment.text == "Hi"


@pytest.mark.parametrize(
    ("version", "tested"), [("0.70.0", True), ("0.97.0", True), ("0.99.1", False)]
)
async def test_version_supported(version: str, tested: bool) -> None:
    mock = Recorder({"/api/version": ok({"currentVersion": version})})
    result = await mock.client().session("t").version()
    assert result.tested is tested
    assert str(result.version) == version


@pytest.mark.parametrize("body", [None, {}, {"currentVersion": ""}])
async def test_version_not_reported(body: dict[str, str] | None) -> None:
    # Docmost answers with an empty body when its own request to GitHub fails.
    mock = Recorder({"/api/version": ok(body)})
    result = await mock.client().session("t").version()
    assert result.version is None
    assert result.tested is False


async def test_version_too_old() -> None:
    mock = Recorder({"/api/version": ok({"currentVersion": "0.25.3"})})
    with pytest.raises(UnsupportedDocmostVersionError, match=r"0\.70\.0 or newer"):
        await mock.client().session("t").version()


async def test_check_reachable() -> None:
    def health(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json={"status": "ok"})

    await Recorder({"/api/health": health}).client().check_reachable()

    with pytest.raises(DocmostUnavailableError):
        await Recorder({"/api/health": error(503, "down")}).client().check_reachable()
