"""Tools about the signed-in member."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth import require_scopes

from docmost_mcp_remote.auth import current_scopes
from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.docmost import DocmostBackend
from docmost_mcp_remote.members import MemberService
from docmost_mcp_remote.tools.common import as_member


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
