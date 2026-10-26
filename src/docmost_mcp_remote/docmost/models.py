"""Typed views of the Docmost objects the server uses.

Only the fields the server needs are declared; unknown fields are ignored so
that new Docmost releases do not break parsing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, frozen=True)


class _PageBase(_Model):
    id: str
    slug_id: str = Field(alias="slugId")
    title: str | None = None
    icon: str | None = None
    parent_page_id: str | None = Field(default=None, alias="parentPageId")
    space_id: str = Field(alias="spaceId")


class UserRef(_Model):
    id: str
    name: str | None = None


class CurrentUser(_Model):
    id: str
    name: str | None = None
    email: str
    role: str | None = None
    workspace_id: str = Field(alias="workspaceId")


class SpaceRef(_Model):
    id: str
    name: str | None = None
    slug: str | None = None


class Space(_Model):
    id: str
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    visibility: str | None = None
    member_role: str | None = None
    member_count: int | None = Field(default=None, alias="memberCount")
    created_at: datetime | None = Field(default=None, alias="createdAt")

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Space:
        membership = data.get("membership") or {}
        return cls.model_validate({**data, "member_role": membership.get("role")})


class SpaceMember(_Model):
    """A user or a group with a role in a space."""

    id: str
    type: Literal["user", "group"]
    name: str | None = None
    email: str | None = None
    role: str | None = None
    member_count: int | None = Field(default=None, alias="memberCount")


class WorkspaceMember(_Model):
    id: str
    name: str | None = None
    email: str | None = None
    role: str | None = None
    last_login_at: datetime | None = Field(default=None, alias="lastLoginAt")
    deactivated_at: datetime | None = Field(default=None, alias="deactivatedAt")


class Group(_Model):
    id: str
    name: str
    description: str | None = None
    member_count: int | None = Field(default=None, alias="memberCount")
    is_default: bool | None = Field(default=None, alias="isDefault")


class PageSummary(_PageBase):
    """A page in a list: tree, recent pages or Trash."""

    position: str | None = None
    has_children: bool | None = Field(default=None, alias="hasChildren")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
    deleted_at: datetime | None = Field(default=None, alias="deletedAt")


class Page(_PageBase):
    """A single page with its body as Markdown."""

    content: str = ""
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
    deleted_at: datetime | None = Field(default=None, alias="deletedAt")
    creator: UserRef | None = None
    last_updated_by: UserRef | None = Field(default=None, alias="lastUpdatedBy")
    space: SpaceRef | None = None
    can_edit: bool | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Page:
        content = data.get("content")
        permissions = data.get("permissions") or {}
        return cls.model_validate(
            {
                **data,
                "content": content if isinstance(content, str) else "",
                "can_edit": permissions.get("canEdit"),
            }
        )


class CopiedPage(_PageBase):
    """The top page of a copy made by ``pages/duplicate``."""

    space: SpaceRef | None = None
    child_page_ids: list[str] = Field(default_factory=list, alias="childPageIds")


class LinkedPage(_PageBase):
    """A page in a backlink or label listing."""

    space: SpaceRef | None = None
    updated_at: datetime | None = Field(default=None, alias="updatedAt")


class SuggestedUser(_Model):
    id: str
    name: str | None = None
    email: str | None = None


class SuggestedGroup(_Model):
    id: str
    name: str
    description: str | None = None


class Suggestions(_Model):
    """Answer of ``search/suggest``: matches by name, for mentions and quick lookups."""

    users: list[SuggestedUser] = Field(default_factory=list)
    groups: list[SuggestedGroup] = Field(default_factory=list)
    pages: list[LinkedPage] = Field(default_factory=list)


ExportFormat = Literal["markdown", "html"]


class Attachment(_Model):
    """A file uploaded to a page."""

    id: str
    file_name: str = Field(alias="fileName")
    file_size: int | None = Field(default=None, alias="fileSize")
    mime_type: str | None = Field(default=None, alias="mimeType")
    page_id: str | None = Field(default=None, alias="pageId")
    space_id: str | None = Field(default=None, alias="spaceId")
    creator: UserRef | None = None
    created_at: datetime | None = Field(default=None, alias="createdAt")


class Label(_Model):
    id: str
    name: str


class SearchHit(_PageBase):
    highlight: str | None = None
    rank: float | None = None
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
    space: SpaceRef | None = None
    space_id: str = Field(default="", alias="spaceId")

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> SearchHit:
        space = data.get("space") or {}
        return cls.model_validate({"spaceId": space.get("id", ""), **data})


class Comment(_Model):
    id: str
    page_id: str = Field(alias="pageId")
    parent_comment_id: str | None = Field(default=None, alias="parentCommentId")
    space_id: str | None = Field(default=None, alias="spaceId")
    creator_id: str | None = Field(default=None, alias="creatorId")
    text: str = ""
    creator: UserRef | None = None
    created_at: datetime | None = Field(default=None, alias="createdAt")
    edited_at: datetime | None = Field(default=None, alias="editedAt")
    resolved_at: datetime | None = Field(default=None, alias="resolvedAt")

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Comment:
        from docmost_mcp_remote.docmost.prosemirror import doc_to_text

        content = data.get("content")
        text = doc_to_text(content) if isinstance(content, dict) else ""
        return cls.model_validate({**data, "text": text})


class HistoryEntry(_Model):
    """One saved version of a page in Docmost's page history."""

    id: str
    page_id: str = Field(alias="pageId")
    title: str | None = None
    created_at: datetime | None = Field(default=None, alias="createdAt")
    last_updated_by: UserRef | None = Field(default=None, alias="lastUpdatedBy")
    contributors: list[UserRef] = Field(default_factory=list)


class HistoryVersion(HistoryEntry):
    """A history entry with its body, converted from ProseMirror JSON to Markdown."""

    space_id: str | None = Field(default=None, alias="spaceId")
    content: str = ""
    #: The version as Docmost stores it, for a restore without conversion.
    document: dict[str, Any] | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> HistoryVersion:
        from docmost_mcp_remote.docmost.prosemirror import doc_to_markdown

        content = data.get("content")
        if not isinstance(content, dict):
            return cls.model_validate({**data, "content": ""})
        return cls.model_validate(
            {**data, "content": doc_to_markdown(content), "document": content}
        )


class Paginated[T](_Model):
    items: list[T]
    next_cursor: str | None = None
    has_next_page: bool = False


BodyOperation = Literal["append", "prepend", "replace"]
BacklinkDirection = Literal["incoming", "outgoing"]
SpaceRole = Literal["admin", "writer", "reader"]
