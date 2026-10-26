"""The interface between the MCP server and a Docmost edition.

``DocmostClient`` is shared by the whole server and creates sessions.
``DocmostBackend`` is one member's session: every call runs with that
member's Docmost rights. A future Enterprise backend implements the same
two protocols.
"""

from __future__ import annotations

from typing import Any, Protocol

from docmost_mcp_remote.docmost.downloads import Download
from docmost_mcp_remote.docmost.models import (
    Attachment,
    BacklinkDirection,
    BodyOperation,
    Comment,
    CopiedPage,
    CurrentUser,
    ExportFormat,
    Group,
    HistoryEntry,
    HistoryVersion,
    Invitation,
    InviteRole,
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
    WorkspaceRole,
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

    async def get_page_json(self, page_id: str) -> dict[str, Any]: ...

    async def replace_page_json(self, page_id: str, document: dict[str, Any]) -> None: ...

    async def get_page_document(self, page_id: str) -> str:
        """The page body converted by this server from ProseMirror JSON to Markdown."""
        ...

    async def page_history(
        self, page_id: str, *, cursor: str | None = None, limit: int = 20
    ) -> Paginated[HistoryEntry]: ...

    async def history_version(self, history_id: str) -> HistoryVersion: ...

    async def search(
        self,
        query: str,
        *,
        space_id: str | None = None,
        limit: int = 20,
        title_only: bool = False,
        label_ids: list[str] | None = None,
        creator_id: str | None = None,
    ) -> list[SearchHit]: ...

    async def backlinks(
        self,
        page_id: str,
        direction: BacklinkDirection,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Paginated[LinkedPage]: ...

    async def create_space(
        self, name: str, slug: str, *, description: str | None = None
    ) -> Space: ...

    async def update_space(
        self,
        space_id: str,
        *,
        name: str | None = None,
        slug: str | None = None,
        description: str | None = None,
    ) -> Space: ...

    async def space_members(
        self, space_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> Paginated[SpaceMember]: ...

    async def add_space_members(
        self, space_id: str, role: SpaceRole, *, user_ids: list[str], group_ids: list[str]
    ) -> None: ...

    async def change_space_member_role(
        self,
        space_id: str,
        role: SpaceRole,
        *,
        user_id: str | None = None,
        group_id: str | None = None,
    ) -> None: ...

    async def workspace_members(
        self, *, query: str | None = None, cursor: str | None = None, limit: int = 50
    ) -> Paginated[WorkspaceMember]: ...

    async def groups(
        self, *, query: str | None = None, cursor: str | None = None, limit: int = 50
    ) -> Paginated[Group]: ...

    async def group_members(
        self, group_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> Paginated[WorkspaceMember]: ...

    async def create_group(
        self, name: str, *, description: str | None = None, user_ids: list[str] | None = None
    ) -> Group: ...

    async def update_group(
        self, group_id: str, *, name: str | None = None, description: str | None = None
    ) -> Group: ...

    async def add_group_members(self, group_id: str, user_ids: list[str]) -> None: ...

    async def invitations(
        self, *, query: str | None = None, cursor: str | None = None, limit: int = 50
    ) -> Paginated[Invitation]: ...

    async def invite(self, emails: list[str], role: InviteRole, group_ids: list[str]) -> None: ...

    async def resend_invitation(self, invitation_id: str) -> None: ...

    async def revoke_invitation(self, invitation_id: str) -> None: ...

    async def change_workspace_role(self, user_id: str, role: WorkspaceRole) -> None: ...

    async def set_member_active(self, user_id: str, active: bool) -> None: ...

    async def suggest(
        self,
        query: str,
        *,
        pages: bool = True,
        users: bool = False,
        groups: bool = False,
        space_id: str | None = None,
        limit: int = 10,
    ) -> Suggestions: ...

    async def labels(self, *, cursor: str | None = None, limit: int = 100) -> Paginated[Label]: ...

    async def page_labels(
        self, page_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> Paginated[Label]: ...

    async def pages_by_label(
        self, name: str, *, space_id: str | None = None, cursor: str | None = None, limit: int = 50
    ) -> Paginated[LinkedPage]: ...

    async def add_labels(self, page_id: str, names: list[str]) -> list[Label]: ...

    async def remove_label(self, page_id: str, label_id: str) -> None: ...

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
        self,
        page_id: str,
        text: str,
        *,
        parent_comment_id: str | None = None,
        mentions: list[dict[str, Any]] | None = None,
    ) -> Comment: ...

    async def update_comment(self, comment_id: str, text: str) -> Comment: ...

    async def list_trash(
        self, space_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> Paginated[PageSummary]: ...

    async def move_to_trash(self, page_id: str) -> None: ...

    async def restore_from_trash(self, page_id: str) -> None: ...

    async def export_page(
        self,
        page_id: str,
        format: ExportFormat,
        *,
        include_children: bool = False,
        include_attachments: bool = False,
    ) -> Download:
        """One page as a Markdown or HTML file, or a zip with its children or files."""
        ...

    async def export_space(
        self, space_id: str, format: ExportFormat, *, include_attachments: bool = False
    ) -> Download:
        """A whole space as a zip."""
        ...

    async def attachment_info(self, attachment_id: str) -> Attachment: ...

    async def page_attachments(
        self, page_id: str, *, cursor: str | None = None, limit: int = 50
    ) -> Paginated[Attachment]: ...

    async def download_attachment(self, attachment_id: str, file_name: str) -> Download: ...

    async def upload_attachment(
        self, page_id: str, file_name: str, content: bytes, mime_type: str
    ) -> Attachment: ...


class DocmostClient(Protocol):
    async def check_reachable(self) -> None: ...

    async def login(self, email: str, password: str) -> str:
        """Sign in and return the Docmost session token."""
        ...

    def session(self, token: str) -> DocmostBackend: ...

    async def aclose(self) -> None: ...
