"""Docmost Community Edition backend over the internal HTTP API.

Every endpoint is ``POST /api/<path>`` with a JSON body. Successful answers
are wrapped as ``{"data": ..., "success": true}``. The member's session token
is sent as a bearer token.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from docmost_mcp_remote.docmost.errors import (
    DocmostAuthError,
    DocmostBadRequestError,
    DocmostError,
    DocmostForbiddenError,
    DocmostNotFoundError,
    DocmostResponseTooLargeError,
    DocmostUnavailableError,
)
from docmost_mcp_remote.docmost.links import mark_internal_links
from docmost_mcp_remote.docmost.models import (
    BacklinkDirection,
    BodyOperation,
    Comment,
    CopiedPage,
    CurrentUser,
    Group,
    HistoryEntry,
    HistoryVersion,
    Label,
    LinkedPage,
    Page,
    PageSummary,
    Paginated,
    SearchHit,
    Space,
    SpaceMember,
    SpaceRole,
    Suggestions,
    WorkspaceMember,
)
from docmost_mcp_remote.docmost.prosemirror import doc_to_markdown, text_to_doc
from docmost_mcp_remote.docmost.version import VersionCheck, check_version

logger = logging.getLogger(__name__)

#: Docmost rejects larger page sizes.
MAX_PAGE_SIZE = 100
_DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024


def _limit(value: int) -> int:
    return max(1, min(value, MAX_PAGE_SIZE))


def _error_message(payload: Any) -> str:
    """Pick Docmost's own short message out of an error body."""
    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, list):
            return "; ".join(str(part) for part in message)
        if isinstance(message, str):
            return message
    return "no details"


class CeDocmostClient:
    """Server-wide client: owns the connection pool and creates member sessions."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._max_response_bytes = max_response_bytes
        self.web_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/api",
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            headers={"accept": "application/json", "user-agent": "docmost-mcp-remote"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def check_reachable(self) -> None:
        """Check that Docmost answers its public health endpoint."""
        try:
            response = await self._http.get("/health")
        except httpx.HTTPError as exc:
            raise DocmostUnavailableError(
                f"Docmost is not reachable: {type(exc).__name__}"
            ) from None
        if response.status_code != 200:
            raise DocmostUnavailableError(
                f"Docmost health check answered HTTP {response.status_code}"
            )

    async def login(self, email: str, password: str) -> str:
        reply = await self._send("auth/login", {"email": email, "password": password}, None)
        token = reply.cookies.get("authToken")
        if not token:
            raise DocmostError("Docmost accepted the sign-in but returned no session token")
        return token

    def session(self, token: str) -> CeDocmostSession:
        return CeDocmostSession(self, token)

    async def call(self, path: str, body: dict[str, Any], token: str) -> Any:
        """POST to ``/api/<path>`` and return the ``data`` member of the answer."""
        payload = (await self._send(path, body, token)).json()
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    async def _send(self, path: str, body: dict[str, Any], token: str | None) -> _Reply:
        headers = {"authorization": f"Bearer {token}"} if token else {}
        request = self._http.build_request("POST", path, json=body, headers=headers)
        try:
            response = await self._http.send(request, stream=True)
        except httpx.TimeoutException:
            raise DocmostUnavailableError(f"Docmost timed out on {path}") from None
        except httpx.HTTPError as exc:
            raise DocmostUnavailableError(
                f"Docmost is not reachable: {type(exc).__name__}"
            ) from None
        try:
            content = await self._read_limited(response, path)
        finally:
            await response.aclose()
        reply = _Reply(
            status=response.status_code,
            content_type=response.headers.get("content-type", ""),
            cookies=dict(response.cookies),
            content=content,
        )
        reply.raise_for_status(path)
        return reply

    async def _read_limited(self, response: httpx.Response, path: str) -> bytes:
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self._max_response_bytes:
            raise DocmostResponseTooLargeError(f"Docmost response to {path} is too large")
        chunks: list[bytes] = []
        size = 0
        try:
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self._max_response_bytes:
                    raise DocmostResponseTooLargeError(f"Docmost response to {path} is too large")
                chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise DocmostUnavailableError(
                f"Docmost connection failed while reading {path}: {type(exc).__name__}"
            ) from None
        return b"".join(chunks)


@dataclass(frozen=True, slots=True)
class _Reply:
    status: int
    content_type: str
    cookies: dict[str, str]
    content: bytes

    def json(self) -> Any:
        if "application/json" not in self.content_type:
            raise DocmostUnavailableError("Docmost answered with a non-JSON response")
        try:
            return json.loads(self.content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise DocmostUnavailableError("Docmost answered with invalid JSON") from None

    def raise_for_status(self, path: str) -> None:
        if self.status < 400:
            return
        try:
            message = _error_message(json.loads(self.content))
        except (json.JSONDecodeError, UnicodeDecodeError):
            message = "no details"
        if self.status == 401:
            raise DocmostAuthError(message)
        if self.status == 403:
            raise DocmostForbiddenError(message)
        if self.status == 404:
            raise DocmostNotFoundError(message)
        if self.status in (400, 422):
            raise DocmostBadRequestError(message)
        if self.status == 429:
            raise DocmostUnavailableError("Docmost is rate limiting requests, try again later")
        raise DocmostUnavailableError(f"Docmost answered HTTP {self.status} on {path}")


def _paginated[T](data: Any, items: list[T]) -> Paginated[T]:
    meta = data.get("meta") or {} if isinstance(data, dict) else {}
    return Paginated[T](
        items=items,
        next_cursor=meta.get("nextCursor"),
        has_next_page=bool(meta.get("hasNextPage")),
    )


def _items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        data = data.get("items", [])
    return [item for item in data or [] if isinstance(item, dict)]


class CeDocmostSession:
    """One member's session; implements ``DocmostBackend``."""

    def __init__(self, client: CeDocmostClient, token: str) -> None:
        self._client = client
        self._token = token

    def __repr__(self) -> str:
        return "CeDocmostSession(<token hidden>)"

    async def _call(self, path: str, body: dict[str, Any]) -> Any:
        return await self._client.call(path, body, self._token)

    async def current_user(self) -> CurrentUser:
        data = await self._call("users/me", {})
        return CurrentUser.model_validate(data["user"])

    async def version(self) -> VersionCheck:
        data = await self._call("version", {})
        reported = data.get("currentVersion") if isinstance(data, dict) else None
        return check_version(str(reported or ""))

    async def list_spaces(self, *, cursor: str | None = None, limit: int = 50) -> Paginated[Space]:
        data = await self._call("spaces", {"limit": _limit(limit), "cursor": cursor})
        return _paginated(data, [Space.from_api(item) for item in _items(data)])

    async def get_space(self, space_id: str) -> Space:
        data = await self._call("spaces/info", {"spaceId": space_id})
        return Space.from_api(data)

    async def create_space(self, name: str, slug: str, *, description: str | None = None) -> Space:
        body: dict[str, Any] = {"name": name, "slug": slug}
        if description is not None:
            body["description"] = description
        data = await self._call("spaces/create", body)
        return Space.from_api(data)

    async def update_space(
        self,
        space_id: str,
        *,
        name: str | None = None,
        slug: str | None = None,
        description: str | None = None,
    ) -> Space:
        body: dict[str, Any] = {"spaceId": space_id}
        for key, value in (("name", name), ("slug", slug), ("description", description)):
            if value is not None:
                body[key] = value
        data = await self._call("spaces/update", body)
        return Space.from_api(data)

    async def space_members(
        self, space_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> Paginated[SpaceMember]:
        data = await self._call(
            "spaces/members", {"spaceId": space_id, "limit": _limit(limit), "cursor": cursor}
        )
        return _paginated(data, [SpaceMember.model_validate(item) for item in _items(data)])

    async def add_space_members(
        self, space_id: str, role: SpaceRole, *, user_ids: list[str], group_ids: list[str]
    ) -> None:
        await self._call(
            "spaces/members/add",
            {"spaceId": space_id, "role": role, "userIds": user_ids, "groupIds": group_ids},
        )

    async def change_space_member_role(
        self,
        space_id: str,
        role: SpaceRole,
        *,
        user_id: str | None = None,
        group_id: str | None = None,
    ) -> None:
        body: dict[str, Any] = {"spaceId": space_id, "role": role}
        if user_id:
            body["userId"] = user_id
        if group_id:
            body["groupId"] = group_id
        await self._call("spaces/members/change-role", body)

    async def workspace_members(
        self, *, query: str | None = None, cursor: str | None = None, limit: int = 50
    ) -> Paginated[WorkspaceMember]:
        body: dict[str, Any] = {"limit": _limit(limit), "cursor": cursor}
        if query:
            body["query"] = query
        data = await self._call("workspace/members", body)
        return _paginated(data, [WorkspaceMember.model_validate(item) for item in _items(data)])

    async def suggest(
        self,
        query: str,
        *,
        pages: bool = True,
        users: bool = False,
        groups: bool = False,
        space_id: str | None = None,
        limit: int = 10,
    ) -> Suggestions:
        body: dict[str, Any] = {
            "query": query,
            "includePages": pages,
            "includeUsers": users,
            "includeGroups": groups,
            "limit": _limit(limit),
        }
        if space_id:
            body["spaceId"] = space_id
        data = await self._call("search/suggest", body)
        return Suggestions.model_validate(data or {})

    async def groups(
        self, *, query: str | None = None, cursor: str | None = None, limit: int = 50
    ) -> Paginated[Group]:
        body: dict[str, Any] = {"limit": _limit(limit), "cursor": cursor}
        if query:
            body["query"] = query
        data = await self._call("groups", body)
        return _paginated(data, [Group.model_validate(item) for item in _items(data)])

    async def list_pages(
        self,
        space_id: str,
        *,
        parent_page_id: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Paginated[PageSummary]:
        body: dict[str, Any] = {"spaceId": space_id, "limit": _limit(limit), "cursor": cursor}
        if parent_page_id:
            body["pageId"] = parent_page_id
        data = await self._call("pages/sidebar-pages", body)
        return _paginated(data, [PageSummary.model_validate(item) for item in _items(data)])

    async def recent_pages(
        self, *, space_id: str | None = None, cursor: str | None = None, limit: int = 20
    ) -> Paginated[PageSummary]:
        body: dict[str, Any] = {"limit": _limit(limit), "cursor": cursor}
        if space_id:
            body["spaceId"] = space_id
        data = await self._call("pages/recent", body)
        return _paginated(data, [PageSummary.model_validate(item) for item in _items(data)])

    async def get_page(self, page_id: str) -> Page:
        data = await self._call("pages/info", {"pageId": page_id, "format": "markdown"})
        return Page.from_api(data)

    async def breadcrumbs(self, page_id: str) -> list[PageSummary]:
        data = await self._call("pages/breadcrumbs", {"pageId": page_id})
        return [PageSummary.model_validate(item) for item in _items(data)]

    async def get_page_document(self, page_id: str) -> str:
        data = await self._call("pages/info", {"pageId": page_id, "format": "json"})
        content = data.get("content") if isinstance(data, dict) else None
        return doc_to_markdown(content) if isinstance(content, dict) else ""

    async def page_history(
        self, page_id: str, *, cursor: str | None = None, limit: int = 20
    ) -> Paginated[HistoryEntry]:
        data = await self._call(
            "pages/history", {"pageId": page_id, "limit": _limit(limit), "cursor": cursor}
        )
        return _paginated(data, [HistoryEntry.model_validate(item) for item in _items(data)])

    async def history_version(self, history_id: str) -> HistoryVersion:
        data = await self._call("pages/history/info", {"historyId": history_id})
        return HistoryVersion.from_api(data)

    async def search(
        self,
        query: str,
        *,
        space_id: str | None = None,
        limit: int = 20,
        title_only: bool = False,
        label_ids: list[str] | None = None,
        creator_id: str | None = None,
    ) -> list[SearchHit]:
        body: dict[str, Any] = {"query": query, "limit": _limit(limit)}
        if space_id:
            body["spaceId"] = space_id
        if title_only:
            body["titleOnly"] = True
        if label_ids:
            body["labelIds"] = label_ids
        if creator_id:
            body["creatorId"] = creator_id
        data = await self._call("search", body)
        return [SearchHit.from_api(item) for item in _items(data)][: _limit(limit)]

    async def backlinks(
        self,
        page_id: str,
        direction: BacklinkDirection,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Paginated[LinkedPage]:
        data = await self._call(
            "pages/backlinks",
            {"pageId": page_id, "direction": direction, "limit": _limit(limit), "cursor": cursor},
        )
        return _paginated(data, [LinkedPage.model_validate(item) for item in _items(data)])

    async def labels(self, *, cursor: str | None = None, limit: int = 100) -> Paginated[Label]:
        data = await self._call(
            "labels", {"type": "page", "limit": _limit(limit), "cursor": cursor}
        )
        return _paginated(data, [Label.model_validate(item) for item in _items(data)])

    async def page_labels(
        self, page_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> Paginated[Label]:
        data = await self._call(
            "pages/labels", {"pageId": page_id, "limit": _limit(limit), "cursor": cursor}
        )
        return _paginated(data, [Label.model_validate(item) for item in _items(data)])

    async def pages_by_label(
        self, name: str, *, space_id: str | None = None, cursor: str | None = None, limit: int = 50
    ) -> Paginated[LinkedPage]:
        body: dict[str, Any] = {"name": name, "limit": _limit(limit), "cursor": cursor}
        if space_id:
            body["spaceId"] = space_id
        data = await self._call("labels/pages", body)
        return _paginated(data, [LinkedPage.model_validate(item) for item in _items(data)])

    async def add_labels(self, page_id: str, names: list[str]) -> list[Label]:
        data = await self._call("pages/labels/add", {"pageId": page_id, "names": names})
        return [Label.model_validate(item) for item in _items(data)]

    async def remove_label(self, page_id: str, label_id: str) -> None:
        await self._call("pages/labels/remove", {"pageId": page_id, "labelId": label_id})

    async def list_comments(
        self, page_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> Paginated[Comment]:
        data = await self._call(
            "comments", {"pageId": page_id, "limit": _limit(limit), "cursor": cursor}
        )
        return _paginated(data, [Comment.from_api(item) for item in _items(data)])

    async def create_page(
        self,
        space_id: str,
        title: str,
        *,
        markdown: str = "",
        parent_page_id: str | None = None,
    ) -> Page:
        body: dict[str, Any] = {"spaceId": space_id, "title": title}
        if markdown:
            body["content"] = mark_internal_links(markdown, self._client.web_url)
            body["format"] = "markdown"
        if parent_page_id:
            body["parentPageId"] = parent_page_id
        data = await self._call("pages/create", body)
        return Page.from_api(data)

    async def update_page_body(self, page_id: str, markdown: str, operation: BodyOperation) -> None:
        await self._call(
            "pages/update",
            {
                "pageId": page_id,
                "content": mark_internal_links(markdown, self._client.web_url),
                "operation": operation,
                "format": "markdown",
            },
        )

    async def rename_page(self, page_id: str, title: str) -> None:
        await self._call("pages/update", {"pageId": page_id, "title": title})

    async def move_page(self, page_id: str, *, parent_page_id: str | None, position: str) -> None:
        await self._call(
            "pages/move",
            {"pageId": page_id, "parentPageId": parent_page_id, "position": position},
        )

    async def move_page_to_space(self, page_id: str, space_id: str) -> None:
        await self._call("pages/move-to-space", {"pageId": page_id, "spaceId": space_id})

    async def duplicate_page(self, page_id: str, *, space_id: str | None = None) -> CopiedPage:
        body: dict[str, Any] = {"pageId": page_id}
        if space_id:
            body["spaceId"] = space_id
        data = await self._call("pages/duplicate", body)
        return CopiedPage.model_validate(data)

    async def get_comment(self, comment_id: str) -> Comment:
        data = await self._call("comments/info", {"commentId": comment_id})
        return Comment.from_api(data)

    async def create_comment(
        self, page_id: str, text: str, *, parent_comment_id: str | None = None
    ) -> Comment:
        body: dict[str, Any] = {"pageId": page_id, "content": json.dumps(text_to_doc(text))}
        if parent_comment_id:
            body["parentCommentId"] = parent_comment_id
        data = await self._call("comments/create", body)
        return Comment.from_api(data)

    async def update_comment(self, comment_id: str, text: str) -> Comment:
        data = await self._call(
            "comments/update",
            {"commentId": comment_id, "content": json.dumps(text_to_doc(text))},
        )
        return Comment.from_api(data)

    async def list_trash(
        self, space_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> Paginated[PageSummary]:
        data = await self._call(
            "pages/trash", {"spaceId": space_id, "limit": _limit(limit), "cursor": cursor}
        )
        return _paginated(data, [PageSummary.model_validate(item) for item in _items(data)])

    async def move_to_trash(self, page_id: str) -> None:
        # Only ``pageId`` is sent: the server never asks Docmost for a permanent delete.
        await self._call("pages/delete", {"pageId": page_id})

    async def restore_from_trash(self, page_id: str) -> None:
        await self._call("pages/restore", {"pageId": page_id})
