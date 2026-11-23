"""Tools about the signed-in member."""

from __future__ import annotations

from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import require_scopes
from pydantic import Field

from docmost_mcp_remote.auth import current_scopes
from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.docmost import DocmostBackend
from docmost_mcp_remote.docmost.models import Locale, Name
from docmost_mcp_remote.docmost.version import Version
from docmost_mcp_remote.members import MemberService
from docmost_mcp_remote.tools.common import as_member, require_known_version


def register(mcp: FastMCP, settings: Settings, members: MemberService) -> None:
    @mcp.tool(
        name="whoami",
        description=(
            "Show which Docmost account this connection acts as, the scopes the member "
            "granted to this client, the Docmost version, and the account page where the "
            "member sees and revokes connected apps and tokens. Use it when unsure whose "
            "rights you act with or why a tool is missing."
        ),
        annotations={"readOnlyHint": True, "openWorldHint": False},
        auth=require_scopes("read"),
    )
    async def whoami() -> dict[str, Any]:
        async def action(backend: DocmostBackend) -> dict[str, Any]:
            user = await backend.current_user()
            check = await backend.version()
            return {
                "name": user.name,
                "email": user.email,
                "docmost_role": user.role,
                "scopes": sorted(current_scopes()),
                "docmost_version": str(check.version) if check.version else "unknown",
                "account_url": f"{settings.public_base}/account",
            }

        return await as_member(members, action)

    @mcp.tool(
        name="update_my_profile",
        description=(
            "Change only your own display name, language or IANA time zone. "
            "Cannot change passwords, email, roles or another member. Needs Docmost 0.98+."
        ),
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
        auth=require_scopes("write"),
    )
    async def update_my_profile(
        name: Annotated[
            Name | None, Field(min_length=1, max_length=100, description="Your display name.")
        ] = None,
        locale: Annotated[Locale | None, Field(description="Your interface language.")] = None,
        timezone: Annotated[
            str | None, Field(max_length=100, description="IANA time zone, e.g. Europe/Moscow.")
        ] = None,
    ) -> dict[str, Any]:
        if name is None and locale is None and timezone is None:
            raise ToolError("Give at least one of name, locale or timezone.")
        if name is not None and not name.strip():
            raise ToolError("The display name cannot be blank.")
        if timezone is not None:
            try:
                ZoneInfo(timezone)
            except (ValueError, ZoneInfoNotFoundError):
                raise ToolError("Give a valid IANA time zone, for example Europe/Moscow.") from None

        async def action(backend: DocmostBackend) -> dict[str, Any]:
            await require_known_version(backend, Version(0, 98, 0))
            await backend.update_own_profile(name=name, locale=locale, timezone=timezone)
            user = await backend.current_user()
            for key, value in (("name", name), ("locale", locale), ("timezone", timezone)):
                if value is not None and getattr(user, key) != value:
                    raise ToolError("Docmost did not confirm the requested profile update.")
            return {
                "id": user.id,
                "name": user.name,
                "locale": user.locale,
                "timezone": user.timezone,
            }

        return await as_member(members, action)
