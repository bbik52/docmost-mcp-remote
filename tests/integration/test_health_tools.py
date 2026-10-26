"""The space health check against real Docmost."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, OWNER

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def server(migrated_database: str, tokens: dict[str, str]) -> Iterator[RunningServer]:
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as running:
        yield running


def test_check_space_health(server: RunningServer) -> None:
    token = server.token(scopes=("write", "delete", "admin"), email=OWNER[0], password=OWNER[1])
    slug = f"health{uuid.uuid4().hex[:8]}"
    space = server.call(token, "create_space", {"name": "Health", "slug": slug})["id"]

    def create(title: str, content: str = "") -> dict[str, str]:
        args = {"space_id": space, "title": title, "content": content}
        return dict(server.call(token, "create_page", args))

    guide = create("Guide", "Intro")
    gone = create("Gone", "Soon in Trash")
    create("Guide", "Another guide")
    create("Empty")
    create(
        "Links",
        f"See [the guide]({guide['url']}) and [the old page]({gone['url']}).",
    )
    server.call(token, "trash_page", {"page": gone["id"]})

    data = server.call(token, "check_space_health", {"space_id": space})
    assert data["pages_checked"] == 4
    assert data["summary"]["empty"] == 1
    assert data["summary"]["duplicate_titles"] == 1
    assert [(item["title"], item["problem"]) for item in data["broken_links"]] == [
        ("Links", "page is in Trash")
    ]
    assert data["top_editors"][0]["pages"] == 4
