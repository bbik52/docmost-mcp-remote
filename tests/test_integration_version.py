"""Pinned integration images remain identifiable when Docmost's lookup fails."""

from unittest.mock import Mock

import pytest

from docmost_mcp_remote.docmost.version import Version
from tests.harness import RunningServer
from tests.integration.conftest import reported_version


@pytest.mark.parametrize(
    ("reported", "tag", "expected"),
    [
        (None, "0.80.1", Version(0, 80, 1)),
        (None, "0.98.0", Version(0, 98, 0)),
        (None, "latest", None),
        ("0.97.0", "0.98.0", Version(0, 97, 0)),
    ],
)
def test_reported_version_falls_back_to_pinned_image(
    monkeypatch: pytest.MonkeyPatch, reported: str | None, tag: str, expected: Version | None
) -> None:
    monkeypatch.setenv("DOCMOST_VERSION", tag)
    server = Mock(spec=RunningServer)
    server.call.return_value = {"docmost_version": reported}
    assert reported_version(server, "test-token") == expected
