"""Resolve and reopen Community Edition discussions with real authorization."""

from __future__ import annotations

import os
import uuid

import pytest
from fastmcp.exceptions import ToolError

from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, MEMBER, OWNER

pytestmark = pytest.mark.integration


def test_resolve_and_reopen(migrated_database: str, tokens: dict[str, str]) -> None:
    if os.environ.get("DOCMOST_VERSION") not in {"0.98.0", "latest"}:
        pytest.skip("Discussion resolution needs Docmost CE 0.98+")
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as server:
        token = server.token(scopes=("write", "admin"), email=OWNER[0], password=OWNER[1])
        slug = f"r{uuid.uuid4().hex[:10]}"
        space = server.call(token, "create_space", {"name": "Resolution", "slug": slug})
        page = server.call(token, "create_page", {"space_id": space["id"], "title": "Discussion"})
        comment = server.call(token, "add_comment", {"page": page["id"], "text": "Review me"})
        assert server.call(token, "resolve_comment", {"comment_id": comment["id"]})["resolved"]
        assert not server.call(token, "reopen_comment", {"comment_id": comment["id"]})["resolved"]
        member = server.token(scopes=("write",), email=MEMBER[0], password=MEMBER[1])
        with pytest.raises(ToolError):
            server.call(member, "resolve_comment", {"comment_id": comment["id"]})
        comments = server.call(token, "list_comments", {"page_id": page["id"]})["comments"]
        assert comments[0]["resolved"] is False
