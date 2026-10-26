"""Resources and argument completion against real Docmost."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import mcp.types as mt
import pytest

from docmost_mcp_remote.tools.resources import PAGE_URI
from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, MEMBER

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def server(migrated_database: str, tokens: dict[str, str]) -> Iterator[RunningServer]:
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as running:
        yield running


def test_pick_and_read_a_page(server: RunningServer) -> None:
    token = server.token(scopes=("write",), email=MEMBER[0], password=MEMBER[1])
    unique = uuid.uuid4().hex[:10]
    spaces = server.call(token, "list_spaces")["spaces"]
    general = next(space["id"] for space in spaces if space["slug"] == "general")
    created = server.call(
        token,
        "create_page",
        {"space_id": general, "title": f"Resource {unique}", "content": "Body text"},
    )

    assert "slug general" in server.read(token, "docmost://spaces")

    ref = mt.ResourceTemplateReference(type="ref/resource", uri=PAGE_URI)
    picked = server.complete(token, ref, "page", f"Resource {unique}")
    assert picked == [f"resource-{unique}-{created['slug_id']}"]

    text = server.read(token, f"docmost://pages/{picked[0]}")
    assert f"# Resource {unique}" in text
    assert "Body text" in text
    assert f"Page id: {created['id']}" in text
