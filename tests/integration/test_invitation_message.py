from __future__ import annotations

import os
import uuid

import pytest

from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, OWNER

pytestmark = pytest.mark.integration


def test_invite_with_personal_message(migrated_database: str, tokens: dict[str, str]) -> None:
    if os.environ.get("DOCMOST_VERSION") not in {"0.98.0", "latest"}:
        pytest.skip("Invitation messages need Docmost 0.98+")
    email = f"message-{uuid.uuid4().hex[:10]}@example.com"
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as server:
        token = server.token(scopes=("admin",), email=OWNER[0], password=OWNER[1])
        result = server.call(
            token, "invite_people", {"emails": [email], "message": "Welcome to the test workspace"}
        )
        assert result["invited"] == [email]
        pending = server.call(token, "list_invitations", {"query": email})["invitations"]
        assert len(pending) == 1
        server.call(token, "revoke_invitation", {"invitation_id": pending[0]["id"]})
