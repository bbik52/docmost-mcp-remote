from __future__ import annotations

import os

import pytest

from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, OWNER

pytestmark = pytest.mark.integration


def test_profile_read_update_and_restore(migrated_database: str, tokens: dict[str, str]) -> None:
    if os.environ.get("DOCMOST_VERSION") not in {"0.98.0", "latest"}:
        pytest.skip("Profiles need Docmost 0.98+")
    with RunningServer(
        docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True, allowed_spaces="general"
    ) as server:
        token = server.token(scopes=("write",), email=OWNER[0], password=OWNER[1])
        original = server.call(token, "get_member_profile")
        profile = original["profile"]
        assert profile["email"] == OWNER[0]
        assert all(s["slug"] == "general" for s in original["spaces"]["spaces"])
        try:
            changed = server.call(
                token,
                "update_my_profile",
                {"name": "Profile integration", "locale": "ru-RU", "timezone": "Europe/Moscow"},
            )
            assert changed["name"] == "Profile integration"
            assert changed["locale"] == "ru-RU"
            again = server.call(token, "get_member_profile")["profile"]
            assert again["name"] == "Profile integration"
            assert again["timezone"] == "Europe/Moscow"
        finally:
            server.call(
                token,
                "update_my_profile",
                {
                    "name": profile["name"],
                    "locale": profile["locale"] or "en-US",
                    "timezone": profile["timezone"] or "UTC",
                },
            )
