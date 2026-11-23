from __future__ import annotations

import os
import uuid

import pytest
from fastmcp.exceptions import ToolError

from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, MEMBER, OWNER

pytestmark = pytest.mark.integration


def test_archive_restore_with_space_allowlist(
    migrated_database: str, tokens: dict[str, str]
) -> None:
    if os.environ.get("DOCMOST_VERSION") not in {"0.98.0", "latest"}:
        pytest.skip("Space archiving needs Docmost 0.98+")
    slug = f"ar{uuid.uuid4().hex[:8]}"
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as server:
        admin = server.token(scopes=("admin",), email=OWNER[0], password=OWNER[1])
        space = server.call(admin, "create_space", {"name": "Archive controls", "slug": slug})
    with RunningServer(
        docmost_url=DOCMOST_URL,
        docmost_allow_insecure_http=True,
        allowed_spaces=slug,
    ) as server:
        admin = server.token(scopes=("admin",), email=OWNER[0], password=OWNER[1])
        assert server.call(admin, "archive_space", {"space_id": space["id"]})["archived"]
        try:
            assert server.call(admin, "get_space", {"space_id": space["id"]})["archived"]
            member = server.token(scopes=("admin",), email=MEMBER[0], password=MEMBER[1])
            with pytest.raises(ToolError):
                server.call(member, "unarchive_space", {"space_id": space["id"]})
        finally:
            assert not server.call(admin, "unarchive_space", {"space_id": space["id"]})["archived"]
