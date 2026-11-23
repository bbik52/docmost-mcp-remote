from __future__ import annotations

import os
import uuid

import pytest
from fastmcp.exceptions import ToolError

from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, OWNER

pytestmark = pytest.mark.integration


def test_set_and_clear_space_homepage(migrated_database: str, tokens: dict[str, str]) -> None:
    if os.environ.get("DOCMOST_VERSION") not in {"0.98.0", "latest"}:
        pytest.skip("Space homepages need Docmost 0.98+")
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as server:
        token = server.token(scopes=("write", "admin"), email=OWNER[0], password=OWNER[1])
        slug = f"hp{uuid.uuid4().hex[:8]}"
        space = server.call(token, "create_space", {"name": "Home page", "slug": slug})
        page = server.call(token, "create_page", {"space_id": space["id"], "title": "Welcome"})
        set_args = {"space_id": space["id"], "page": page["id"]}
        assert server.call(token, "set_space_homepage", set_args)["home_page_id"] == page["id"]
        try:
            assert (
                server.call(token, "get_space", {"space_id": space["id"]})["home_page_id"]
                == page["id"]
            )
            other = server.call(token, "create_space", {"name": "Other home", "slug": f"o{slug}"})
            with pytest.raises(ToolError, match="of this space"):
                server.call(
                    token, "set_space_homepage", {"space_id": other["id"], "page": page["id"]}
                )
        finally:
            assert (
                server.call(token, "set_space_homepage", {"space_id": space["id"], "page": None})[
                    "home_page_id"
                ]
                is None
            )
