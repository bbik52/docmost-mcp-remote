"""Regression coverage for version-dependent live Markdown assertions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from docmost_mcp_remote.docmost.ce import CeDocmostSession
from docmost_mcp_remote.docmost.version import Version
from tests.integration.test_docmost_ce import (
    test_converted_markdown_matches_docmost as check_markdown,
)


def _owner(version: Version | None) -> AsyncMock:
    owner = AsyncMock(spec=CeDocmostSession)
    owner.create_page.return_value = SimpleNamespace(id="page")
    owner.get_page.return_value = SimpleNamespace(content="Text\n\n| | |\n| Name | Value |")
    owner.get_page_document.return_value = "Text\n\n| Name | Value |"
    owner.version.return_value = SimpleNamespace(version=version)
    return owner


@pytest.mark.parametrize("tag", ["0.80.1", "0.96.0"])
async def test_old_image_formatting_with_missing_reported_version(
    monkeypatch: pytest.MonkeyPatch, tag: str
) -> None:
    monkeypatch.setenv("DOCMOST_VERSION", tag)
    await check_markdown(_owner(None), "space", "unique")


@pytest.mark.parametrize("version", [None, Version(0, 97, 0)])
async def test_modern_image_still_requires_exact_markdown(
    monkeypatch: pytest.MonkeyPatch, version: Version | None
) -> None:
    monkeypatch.setenv("DOCMOST_VERSION", "0.97.0")
    with pytest.raises(AssertionError):
        await check_markdown(_owner(version), "space", "unique")


async def test_unknown_version_does_not_assume_modern_formatting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCMOST_VERSION", "latest")
    with pytest.raises(pytest.skip.Exception, match="no versioned image tag"):
        await check_markdown(_owner(None), "space", "unique")
