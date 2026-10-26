"""Labels, backlinks and search filters against real Docmost 0.90 or newer."""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator

import pytest

from docmost_mcp_remote.docmost.version import Version, parse_version
from tests.harness import RunningServer
from tests.integration.conftest import DOCMOST_URL, MEMBER

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def server(migrated_database: str, tokens: dict[str, str]) -> Iterator[RunningServer]:
    with RunningServer(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True) as running:
        yield running


@pytest.fixture(scope="module")
def token(server: RunningServer) -> str:
    token = server.token(scopes=("write",), email=MEMBER[0], password=MEMBER[1])
    reported = server.call(token, "whoami")["docmost_version"]
    if reported is not None and parse_version(reported) < Version(0, 90, 0):
        pytest.skip("labels and backlinks need Docmost 0.90")
    return token


def test_labels(server: RunningServer, token: str) -> None:
    unique = uuid.uuid4().hex[:10]
    spaces = server.call(token, "list_spaces")["spaces"]
    general = next(space["id"] for space in spaces if space["slug"] == "general")
    page = server.call(
        token, "create_page", {"space_id": general, "title": f"Tagged {unique}", "content": "x"}
    )
    label = f"l{unique}"

    added = server.call(token, "add_labels", {"page": page["id"], "labels": [label, "Shared"]})
    assert sorted(item["name"] for item in added["labels"]) == [label, "shared"]
    assert label in {item["name"] for item in server.call(token, "list_labels")["labels"]}

    found = server.call(token, "find_pages_by_label", {"label": label, "space_id": general})
    assert [item["id"] for item in found["pages"]] == [page["id"]]

    removed = server.call(token, "remove_label", {"page": page["id"], "label": label})
    assert [item["name"] for item in removed["labels"]] == ["shared"]
    listed = server.call(token, "list_labels", {"page": page["id"]})["labels"]
    assert [item["name"] for item in listed] == ["shared"]


def test_backlinks(server: RunningServer, token: str) -> None:
    unique = uuid.uuid4().hex[:10]
    spaces = server.call(token, "list_spaces")["spaces"]
    general = next(space["id"] for space in spaces if space["slug"] == "general")
    target = server.call(
        token, "create_page", {"space_id": general, "title": f"Target {unique}", "content": "x"}
    )
    source = server.call(
        token, "create_page", {"space_id": general, "title": f"Source {unique}", "content": "x"}
    )
    server.call(
        token, "update_page", {"page": source["id"], "content": f"See [it]({target['url']})."}
    )

    # Docmost records links when it saves a page version, about a minute after
    # the last edit of a new page.
    incoming: list[str] = []
    for _ in range(90):
        result = server.call(token, "list_backlinks", {"page": target["id"]})
        incoming = [item["id"] for item in result["pages"]]
        if incoming:
            break
        time.sleep(2)
    assert incoming == [source["id"]]
    outgoing = server.call(token, "list_backlinks", {"page": source["id"], "direction": "outgoing"})
    assert [item["id"] for item in outgoing["pages"]] == [target["id"]]
