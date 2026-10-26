"""Spaces, their members and the workspace's people.

Listing is read scope. Creating and changing spaces and giving people a role
in a space need the ``admin`` scope, which a member grants a client only on
purpose; Docmost still checks the member's own rights. Removing members and
deleting spaces are not offered.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

import mcp_types as mt
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import require_scopes
from pydantic import Field

from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.docmost import DocmostBackend
from docmost_mcp_remote.docmost.models import Group, Space, SpaceRole, WorkspaceMember
from docmost_mcp_remote.members import MemberService
from docmost_mcp_remote.tools.common import as_member
from docmost_mcp_remote.tools.confirm import confirm, named
from docmost_mcp_remote.tools.read import Cursor, Limit
from docmost_mcp_remote.tools.spaces import SpacePolicy

_READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
_ADMIN = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

SpaceId = Annotated[str, Field(description="Space id from list_spaces.")]
Role = Annotated[SpaceRole, Field(description="admin, writer or reader.")]
SpaceName = Annotated[str, Field(min_length=2, max_length=100)]
Slug = Annotated[
    str,
    Field(
        min_length=2,
        max_length=100,
        pattern=r"^[A-Za-z0-9]+$",
        description="Short name used in URLs: letters and digits only.",
    ),
]
Description = Annotated[str, Field(max_length=500)]


def _space(space: Space, docmost_base: str) -> dict[str, Any]:
    return {
        "id": space.id,
        "name": space.name,
        "slug": space.slug,
        "description": space.description or None,
        "member_count": space.member_count,
        "url": f"{docmost_base}/s/{space.slug}" if space.slug else None,
    }


def _person(member: WorkspaceMember) -> dict[str, Any]:
    return {
        "id": member.id,
        "name": member.name,
        "email": member.email,
        "role": member.role,
        "deactivated": member.deactivated_at is not None,
        "last_login_at": member.last_login_at.isoformat() if member.last_login_at else None,
    }


def _group(group: Group) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description or None,
        "member_count": group.member_count,
        "is_default": group.is_default,
    }


async def _user_ids(backend: DocmostBackend, refs: list[str]) -> list[str]:
    ids: list[str] = []
    for ref in refs:
        if "@" not in ref:
            ids.append(ref)
            continue
        found = await backend.workspace_members(query=ref, limit=100)
        match = next(
            (item for item in found.items if (item.email or "").lower() == ref.lower()), None
        )
        if match is None:
            raise ToolError(f"No workspace member has the email {ref!r}.")
        ids.append(match.id)
    return ids


async def _group_ids(backend: DocmostBackend, refs: list[str]) -> list[str]:
    ids: list[str] = []
    for ref in refs:
        if _UUID.match(ref):
            ids.append(ref)
            continue
        found = await backend.groups(query=ref, limit=100)
        match = next((item for item in found.items if item.name.lower() == ref.lower()), None)
        if match is None:
            raise ToolError(f"No group is named {ref!r}.")
        ids.append(match.id)
    return ids


def register(mcp: FastMCP, settings: Settings, members: MemberService) -> None:
    policy = SpacePolicy(settings.allowed_spaces)
    docmost_base = str(settings.docmost_url).rstrip("/")

    def ensure_slug_allowed(slug: str) -> None:
        # A space this server could not use afterwards is refused up front.
        if policy.restricted and slug not in settings.allowed_spaces:
            raise ToolError(
                f"This server only works with the spaces in ALLOWED_SPACES, and {slug!r} is not "
                "one of them; ask the server admin to add it first."
            )

    @mcp.tool(
        name="list_space_members",
        description="List the users and groups that have a role in a space.",
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def list_space_members(
        space_id: SpaceId, cursor: Cursor = None, limit: Limit = 50
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            await policy.check(backend, space_id)
            result = await backend.space_members(space_id, cursor=cursor, limit=limit)
            return {
                "space_id": space_id,
                "members": [
                    {
                        "id": item.id,
                        "type": item.type,
                        "name": item.name,
                        "email": item.email,
                        "role": item.role,
                        "member_count": item.member_count,
                    }
                    for item in result.items
                ],
                "next_cursor": result.next_cursor if result.has_next_page else None,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="list_workspace_members",
        description=(
            "List the people in the Docmost workspace with their workspace role, optionally "
            "filtered by a part of their name or email."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def list_workspace_members(
        query: Annotated[str | None, Field(max_length=100)] = None,
        cursor: Cursor = None,
        limit: Limit = 50,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            result = await backend.workspace_members(query=query, cursor=cursor, limit=limit)
            return {
                "members": [_person(item) for item in result.items],
                "next_cursor": result.next_cursor if result.has_next_page else None,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="list_groups",
        description="List the workspace's groups, optionally filtered by a part of their name.",
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def list_groups(
        query: Annotated[str | None, Field(max_length=100)] = None,
        cursor: Cursor = None,
        limit: Limit = 50,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            result = await backend.groups(query=query, cursor=cursor, limit=limit)
            return {
                "groups": [_group(item) for item in result.items],
                "next_cursor": result.next_cursor if result.has_next_page else None,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="create_space",
        description=(
            "Create a space; you become its admin. Needs a Docmost workspace admin or owner."
        ),
        annotations=_ADMIN,
        auth=require_scopes("admin"),
    )
    async def create_space(
        name: SpaceName, slug: Slug, description: Description | None = None
    ) -> dict[str, Any]:
        ensure_slug_allowed(slug)

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            space = await backend.create_space(name, slug, description=description)
            return _space(space, docmost_base)

        return await as_member(members, action)

    @mcp.tool(
        name="update_space",
        description=(
            "Change a space's name, slug or description. Changing the slug changes the "
            "space's URLs. Needs admin rights in the space."
        ),
        annotations=_ADMIN,
        auth=require_scopes("admin"),
    )
    async def update_space(
        space_id: SpaceId,
        name: SpaceName | None = None,
        slug: Slug | None = None,
        description: Description | None = None,
    ) -> dict[str, Any]:
        if name is None and slug is None and description is None:
            raise ToolError("Give at least one of name, slug and description.")

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            await policy.check(backend, space_id)
            if slug is not None and space_id not in settings.allowed_spaces:
                ensure_slug_allowed(slug)
            space = await backend.update_space(
                space_id, name=name, slug=slug, description=description
            )
            return _space(space, docmost_base)

        return await as_member(members, action)

    @mcp.tool(
        name="add_space_members",
        description=(
            "Give users and groups a role in a space. Users are given by email or id, groups "
            "by name or id. People who already have a role keep it; use "
            "change_space_member_role for them. Needs admin rights in the space."
        ),
        annotations=_ADMIN,
        auth=require_scopes("admin"),
    )
    async def add_space_members(
        space_id: SpaceId,
        role: Role,
        users: Annotated[list[str] | None, Field(max_length=25)] = None,
        groups: Annotated[list[str] | None, Field(max_length=25)] = None,
    ) -> dict[str, Any] | mt.InputRequiredResult:
        users = users or []
        groups = groups or []
        if not users and not groups:
            raise ToolError("Give at least one user or group.")

        async def action(backend: DocmostBackend) -> dict[str, Any] | mt.InputRequiredResult:
            await policy.check(backend, space_id)
            user_ids = await _user_ids(backend, users)
            group_ids = await _group_ids(backend, groups)

            async def question() -> str:
                space = await backend.get_space(space_id)
                return (
                    f"Give {', '.join([*users, *groups])} the role {role} in the space "
                    f"{named(space.name)}?"
                )

            asked = await confirm(question)
            if isinstance(asked, mt.InputRequiredResult):
                return asked
            await backend.add_space_members(space_id, role, user_ids=user_ids, group_ids=group_ids)
            return {
                "space_id": space_id,
                "role": role,
                "user_ids": user_ids,
                "group_ids": group_ids,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="change_space_member_role",
        description=(
            "Change the role of one user (email or id) or one group (name or id) in a space. "
            "Docmost keeps at least one admin per space. Needs admin rights in the space."
        ),
        annotations=_ADMIN,
        auth=require_scopes("admin"),
    )
    async def change_space_member_role(
        space_id: SpaceId,
        role: Role,
        user: str | None = None,
        group: str | None = None,
    ) -> dict[str, Any] | mt.InputRequiredResult:
        if (user is None) == (group is None):
            raise ToolError("Give either user or group.")

        async def action(backend: DocmostBackend) -> dict[str, Any] | mt.InputRequiredResult:
            await policy.check(backend, space_id)
            user_id = (await _user_ids(backend, [user]))[0] if user else None
            group_id = (await _group_ids(backend, [group]))[0] if group else None

            async def question() -> str:
                space = await backend.get_space(space_id)
                where = named(space.name)
                return f"Change the role of {user or group} in the space {where} to {role}?"

            asked = await confirm(question)
            if isinstance(asked, mt.InputRequiredResult):
                return asked
            await backend.change_space_member_role(
                space_id, role, user_id=user_id, group_id=group_id
            )
            return {"space_id": space_id, "role": role, "user_id": user_id, "group_id": group_id}

        return await as_member(members, action)
