"""The OAuth browser flow end to end, signing in with a real Docmost account."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, MEMBER
from tests.test_oauth import Flow

pytestmark = pytest.mark.integration


def test_oauth_flow(engine: AsyncEngine, tokens: dict[str, str]) -> None:
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as server:
        flow = Flow(server)
        try:
            flow.sign_in(*MEMBER)
            client_id = flow.client_id()
            granted = flow.tokens(client_id, scopes=("write",))
            refreshed = flow.refresh(client_id, granted["refresh_token"]).json()
            whoami = server.call(refreshed["access_token"], "whoami")
        finally:
            flow.close()
    assert whoami["email"] == MEMBER[0]
    assert whoami["scopes"] == ["read", "write"]
