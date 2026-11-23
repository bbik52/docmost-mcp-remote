from __future__ import annotations

import os

import pytest
from fastmcp.exceptions import ToolError

from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, MEMBER, OWNER

pytestmark = pytest.mark.integration


def test_workspace_language_preserves_members_preferences(
    migrated_database: str, tokens: dict[str, str]
) -> None:
    if os.environ.get("DOCMOST_VERSION") not in {"0.98.0", "latest"}:
        pytest.skip("Workspace language needs Docmost 0.98+")
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as server:
        token = server.token(scopes=("admin",), email=OWNER[0], password=OWNER[1])
        original = server.call(token, "get_workspace_language")["default_locale"]
        profile = server.call(token, "get_member_profile")["profile"]
        chosen = "ru-RU" if original != "ru-RU" else "de-DE"
        try:
            assert (
                server.call(token, "set_workspace_language", {"locale": chosen})["default_locale"]
                == chosen
            )
            assert server.call(token, "get_workspace_language")["default_locale"] == chosen
            assert (
                server.call(token, "get_member_profile")["profile"]["locale"] == profile["locale"]
            )
            member = server.token(scopes=("admin",), email=MEMBER[0], password=MEMBER[1])
            with pytest.raises(ToolError):
                server.call(member, "set_workspace_language", {"locale": "fr-FR"})
        finally:
            server.call(token, "set_workspace_language", {"locale": original})
