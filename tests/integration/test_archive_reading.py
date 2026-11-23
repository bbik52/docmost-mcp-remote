"""Archived pages stay readable through the same space allowlist."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp.exceptions import ToolError

from docmost_mcp_remote.docmost import CeDocmostClient
from docmost_mcp_remote.docmost.ce import CeDocmostSession
from docmost_mcp_remote.docmost.version import Version
from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, OWNER

pytestmark = pytest.mark.integration


async def test_archived_space_search_and_allowlist(
    owner: CeDocmostSession,
    client: CeDocmostClient,
    tokens: dict[str, str],
    space_id: str,
    unique: str,
    migrated_database: str,
) -> None:
    version = (await owner.version()).version
    if version is None or version < Version(0, 98, 0):
        pytest.skip("Archives need a verified Docmost 0.98+")
    space = await owner.create_space(f"Archive {unique}", f"a{unique}")
    page = await owner.create_page(space.id, "Archived page", markdown=f"archive{unique}")
    await client.call("spaces/archive", {"spaceId": space.id}, tokens[OWNER[0]])
    try:

        def check_tools() -> None:
            with RunningServer(
                docmost_url=DOCMOST_URL,
                docmost_allow_insecure_http=True,
                allowed_spaces=space.slug,
            ) as server:
                token = server.token(email=OWNER[0], password=OWNER[1])
                assert server.call(token, "list_spaces")["spaces"] == []
                assert server.call(token, "get_space", {"space_id": space.id})["archived"]
                result = server.call(
                    token, "search", {"query": f"archive{unique}", "include_archived": True}
                )
                assert [hit["id"] for hit in result["results"]] == [page.id]
                assert result["results"][0]["archived"]
                with pytest.raises(ToolError, match="Space not found"):
                    server.call(token, "get_space", {"space_id": space_id})

        await asyncio.to_thread(check_tools)
    finally:
        await client.call("spaces/unarchive", {"spaceId": space.id}, tokens[OWNER[0]])
