"""The interface between the MCP server and a Docmost edition.

``DocmostClient`` is shared by the whole server and creates sessions.
``DocmostBackend`` is one member's session: every call runs with that
member's Docmost rights. A future Enterprise backend implements the same
two protocols.
"""

from __future__ import annotations

from typing import Protocol

from docmost_mcp_remote.docmost.models import (
    BodyOperation,
    Comment,
    CopiedPage,
    CurrentUser,
    Page,
    PageSummary,
    Paginated,
    SearchHit,
    Space,
)
from docmost_mcp_remote.docmost.version import VersionCheck


class DocmostBackend(Protocol):
    async def current_user(self) -> CurrentUser: ...

    async def version(self) -> VersionCheck: ...

    async def list_spaces(
        self, *, cursor: str | None = None, limit: int = 50
    ) -> Paginated[Space]: ...

    async def get_space(self, space_id: str) -> Space: ...

    async def list_pages(
        self,
        space_id: str,
        *,
        parent_page_id: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Paginated[PageSummary]: ...

    async def recent_pages(
        self, *, space_id: str | None = None, cursor: str | None = None, limit: int = 20
    ) -> Paginated[PageSummary]: ...

    async def get_page(self, page_id: str) -> Page: ...

    async def breadcrumbs(self, page_id: str) -> list[PageSummary]: ...

    async def search(
        self, query: str, *, space_id: str | None = None, limit: int = 20
    ) -> list[SearchHit]: ...

    async def list_comments(
        self, page_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> Paginated[Comment]: ...

    async def create_page(
        self,
        space_id: str,
        title: str,
        *,
        markdown: str = "",
        parent_page_id: str | None = None,
    ) -> Page: ...

    async def update_page_body(
        self, page_id: str, markdown: str, operation: BodyOperation
    ) -> None: ...

    async def rename_page(self, page_id: str, title: str) -> None: ...

    async def move_page(
        self, page_id: str, *, parent_page_id: str | None, position: str
    ) -> None: ...

    async def move_page_to_space(self, page_id: str, space_id: str) -> None: ...

    async def duplicate_page(self, page_id: str, *, space_id: str | None = None) -> CopiedPage: ...

    async def get_comment(self, comment_id: str) -> Comment: ...

    async def create_comment(
        self, page_id: str, text: str, *, parent_comment_id: str | None = None
    ) -> Comment: ...

    async def update_comment(self, comment_id: str, text: str) -> Comment: ...

    async def list_trash(
        self, space_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> Paginated[PageSummary]: ...

    async def move_to_trash(self, page_id: str) -> None: ...

    async def restore_from_trash(self, page_id: str) -> None: ...


class DocmostClient(Protocol):
    async def check_reachable(self) -> None: ...

    async def login(self, email: str, password: str) -> str:
        """Sign in and return the Docmost session token."""
        ...

    def session(self, token: str) -> DocmostBackend: ...

    async def aclose(self) -> None: ...
