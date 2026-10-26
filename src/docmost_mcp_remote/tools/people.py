"""The workspace's people: groups, invitations, workspace roles and deactivation.

Listing is read scope; every change needs the ``admin`` scope, and Docmost
still checks that the member is a workspace admin or owner. Removing people
from the workspace or from a group and deleting groups are not offered.
Docmost has no way to create an account or change another person's profile:
people join through an invitation and set their own password.
"""

from __future__ import annotations

from typing import Annotated, Any

import mcp_types as mt
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import require_scopes
from pydantic import Field

from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.docmost import DocmostBackend
from docmost_mcp_remote.docmost.models import Invitation, InviteRole, WorkspaceRole
from docmost_mcp_remote.members import MemberService
from docmost_mcp_remote.tools.common import as_member
from docmost_mcp_remote.tools.confirm import confirm
from docmost_mcp_remote.tools.manage import _group, _group_ids, _person, _user_ids
from docmost_mcp_remote.tools.read import Cursor, Limit

_READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
_ADMIN = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
#: Changing someone's role or access is not undone by repeating the call.
_ADMIN_ACCESS = {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False}
#: An invitation sends an email outside Docmost.
_INVITE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}
MAX_INVITES = 20

GroupRef = Annotated[str, Field(description="Group name or id from list_groups.")]
UserRef = Annotated[str, Field(description="The person's email or user id.")]
Users = Annotated[list[str], Field(min_length=1, max_length=50, description="Emails or user ids.")]
GroupName = Annotated[str, Field(min_length=2, max_length=100, description="Group name.")]
Description = Annotated[str | None, Field(max_length=500, description="Short description.")]
NewGroupName = Annotated[
    str | None, Field(min_length=2, max_length=100, description="New name; left out keeps it.")
]
Email = Annotated[str, Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
InvitationId = Annotated[str, Field(description="Invitation id from list_invitations.")]


def _invitation(item: Invitation) -> dict[str, Any]:
    return {
        "id": item.id,
        "email": item.email,
        "role": item.role,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


async def _pending(backend: DocmostBackend, email: str) -> Invitation | None:
    found = await backend.invitations(query=email, limit=100)
    return next((item for item in found.items if item.email.lower() == email.lower()), None)


def register(mcp: FastMCP, settings: Settings, members: MemberService) -> None:
    async def one_group(backend: DocmostBackend, ref: str) -> str:
        return (await _group_ids(backend, [ref]))[0]

    async def one_user(backend: DocmostBackend, ref: str) -> str:
        return (await _user_ids(backend, [ref]))[0]

    @mcp.tool(
        name="list_group_members",
        description="List the people in a group.",
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def list_group_members(
        group: GroupRef, cursor: Cursor = None, limit: Limit = 50
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            group_id = await one_group(backend, group)
            result = await backend.group_members(group_id, cursor=cursor, limit=limit)
            return {
                "group_id": group_id,
                "members": [_person(item) for item in result.items],
                "next_cursor": result.next_cursor if result.has_next_page else None,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="create_group",
        description=(
            "Create a group, optionally with its first members (emails or user ids). Groups "
            "can then be given a role in spaces with add_space_members. Needs a Docmost "
            "workspace admin or owner."
        ),
        annotations=_ADMIN,
        auth=require_scopes("admin"),
    )
    async def create_group(
        name: GroupName,
        description: Description = None,
        users: Annotated[
            list[str] | None, Field(max_length=50, description="First members: emails or user ids.")
        ] = None,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            user_ids = await _user_ids(backend, users or [])
            created = await backend.create_group(name, description=description, user_ids=user_ids)
            return {**_group(created), "member_count": len(user_ids)}

        return await as_member(members, action)

    @mcp.tool(
        name="update_group",
        description="Rename a group or change its description. Needs a workspace admin or owner.",
        annotations=_ADMIN,
        auth=require_scopes("admin"),
    )
    async def update_group(
        group: GroupRef, name: NewGroupName = None, description: Description = None
    ) -> dict[str, Any]:
        if name is None and description is None:
            raise ToolError("Give name or description.")

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            group_id = await one_group(backend, group)
            updated = await backend.update_group(group_id, name=name, description=description)
            return _group(updated)

        return await as_member(members, action)

    @mcp.tool(
        name="add_group_members",
        description=(
            "Add people (emails or user ids) to a group. They get the group's roles in spaces "
            "at once. Needs a workspace admin or owner."
        ),
        annotations=_ADMIN,
        auth=require_scopes("admin"),
    )
    async def add_group_members(group: GroupRef, users: Users) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            group_id = await one_group(backend, group)
            user_ids = await _user_ids(backend, users)
            await backend.add_group_members(group_id, user_ids)
            return {"group_id": group_id, "added_user_ids": user_ids}

        return await as_member(members, action)

    @mcp.tool(
        name="list_invitations",
        description=(
            "List pending invitations to the workspace, optionally filtered by a part of the email."
        ),
        annotations=_READ_ONLY,
        auth=require_scopes("read"),
    )
    async def list_invitations(
        query: Annotated[
            str | None, Field(max_length=100, description="Part of an email to filter by.")
        ] = None,
        cursor: Cursor = None,
        limit: Limit = 50,
    ) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            result = await backend.invitations(query=query, cursor=cursor, limit=limit)
            return {
                "invitations": [_invitation(item) for item in result.items],
                "next_cursor": result.next_cursor if result.has_next_page else None,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="invite_people",
        description=(
            "Invite people to the workspace by email. Docmost emails each one a link to join "
            "and set a password; they get the workspace role (member or admin) and join the "
            "groups given (names or ids). Emails of people already in the workspace or already "
            "invited are skipped and listed. Check the addresses with the person you work "
            "for before inviting. Needs a workspace admin or owner."
        ),
        annotations=_INVITE,
        auth=require_scopes("admin"),
    )
    async def invite_people(
        emails: Annotated[
            list[Email],
            Field(min_length=1, max_length=MAX_INVITES, description="Email addresses to invite."),
        ],
        role: Annotated[InviteRole, Field(description="member or admin.")] = "member",
        groups: Annotated[
            list[str] | None,
            Field(max_length=25, description="Groups to join on sign-up: names or group ids."),
        ] = None,
    ) -> dict[str, Any] | mt.InputRequiredResult:
        wanted = list(dict.fromkeys(email.strip().lower() for email in emails))

        async def action(backend: DocmostBackend) -> dict[str, Any] | mt.InputRequiredResult:
            group_ids = await _group_ids(backend, groups or [])
            already_members: list[str] = []
            already_invited: list[str] = []
            invite: list[str] = []
            for email in wanted:
                found = await backend.workspace_members(query=email, limit=100)
                if any((item.email or "").lower() == email for item in found.items):
                    already_members.append(email)
                elif await _pending(backend, email):
                    already_invited.append(email)
                else:
                    invite.append(email)
            if invite:
                into = f" and add them to {', '.join(groups or [])}" if groups else ""
                asked = await confirm(
                    f"Invite {', '.join(invite)} to the Docmost workspace as {role}{into}? "
                    "Docmost emails each of them a link to join."
                )
                if isinstance(asked, mt.InputRequiredResult):
                    return asked
                await backend.invite(invite, role, group_ids)
            return {
                "invited": invite,
                "role": role,
                "group_ids": group_ids,
                "already_members": already_members,
                "already_invited": already_invited,
            }

        return await as_member(members, action)

    @mcp.tool(
        name="resend_invitation",
        description=(
            "Send an invitation email again, for someone who did not get it or lost it. Needs a "
            "workspace admin or owner."
        ),
        annotations=_INVITE,
        auth=require_scopes("admin"),
    )
    async def resend_invitation(invitation_id: InvitationId) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            await backend.resend_invitation(invitation_id)
            return {"invitation_id": invitation_id, "resent": True}

        return await as_member(members, action)

    @mcp.tool(
        name="revoke_invitation",
        description=(
            "Cancel a pending invitation; its link stops working. The person can be invited "
            "again later. Needs a workspace admin or owner."
        ),
        annotations=_ADMIN,
        auth=require_scopes("admin"),
    )
    async def revoke_invitation(invitation_id: InvitationId) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            await backend.revoke_invitation(invitation_id)
            return {"invitation_id": invitation_id, "revoked": True}

        return await as_member(members, action)

    @mcp.tool(
        name="change_workspace_role",
        description=(
            "Change a person's workspace role: member, admin or owner. Admins manage people "
            "and spaces; owners also manage the workspace and other owners. Only an owner can "
            "make or change owners, and Docmost keeps at least one owner. Needs a workspace "
            "admin or owner."
        ),
        annotations=_ADMIN_ACCESS,
        auth=require_scopes("admin"),
    )
    async def change_workspace_role(
        user: UserRef,
        role: Annotated[WorkspaceRole, Field(description="member, admin or owner.")],
    ) -> dict[str, Any] | mt.InputRequiredResult:
        async def action(backend: DocmostBackend) -> dict[str, Any] | mt.InputRequiredResult:
            user_id = await one_user(backend, user)
            asked = await confirm(f"Make {user} {role} of the Docmost workspace?")
            if isinstance(asked, mt.InputRequiredResult):
                return asked
            await backend.change_workspace_role(user_id, role)
            return {"user_id": user_id, "role": role}

        return await as_member(members, action)

    @mcp.tool(
        name="deactivate_member",
        description=(
            "Deactivate a person: they are signed out everywhere and cannot sign in, but their "
            "account, pages and roles stay, and activate_member lets them back in. Use it when "
            "someone leaves. You cannot deactivate yourself. Needs a workspace admin or owner."
        ),
        annotations=_ADMIN_ACCESS,
        auth=require_scopes("admin"),
    )
    async def deactivate_member(user: UserRef) -> dict[str, Any] | mt.InputRequiredResult:
        async def action(backend: DocmostBackend) -> dict[str, Any] | mt.InputRequiredResult:
            user_id = await one_user(backend, user)
            asked = await confirm(
                f"Deactivate {user} in Docmost? They are signed out and cannot sign in until "
                "they are activated again."
            )
            if isinstance(asked, mt.InputRequiredResult):
                return asked
            await backend.set_member_active(user_id, False)
            return {"user_id": user_id, "deactivated": True}

        return await as_member(members, action)

    @mcp.tool(
        name="activate_member",
        description=(
            "Let a person deactivated with deactivate_member sign in again, with their roles as "
            "before. Needs a workspace admin or owner."
        ),
        annotations=_ADMIN,
        auth=require_scopes("admin"),
    )
    async def activate_member(user: UserRef) -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            user_id = await one_user(backend, user)
            await backend.set_member_active(user_id, True)
            return {"user_id": user_id, "deactivated": False}

        return await as_member(members, action)
