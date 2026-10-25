from __future__ import annotations

import pytest
from pydantic import ValidationError

from docmost_mcp_remote.config import Settings


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_URL", "https://mcp.example.com")
    monkeypatch.setenv("DOCMOST_URL", "https://docs.example.com")
    monkeypatch.setenv("PORT", "9000")

    settings = Settings()

    assert settings.public_url.host == "mcp.example.com"
    assert settings.port == 9000
    assert not settings.docmost_url_is_insecure


@pytest.mark.parametrize("missing", ["PUBLIC_URL", "DOCMOST_URL"])
def test_required_values(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    values = {"PUBLIC_URL": "https://mcp.example.com", "DOCMOST_URL": "https://docs.example.com"}
    del values[missing]
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match=missing.lower()):
        Settings()


def test_public_url_rejects_http() -> None:
    with pytest.raises(ValidationError, match="PUBLIC_URL must use https"):
        Settings(public_url="http://mcp.example.com", docmost_url="https://docs.example.com")


@pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1:8000"])
def test_public_url_allows_http_on_localhost(url: str) -> None:
    settings = Settings(public_url=url, docmost_url="https://docs.example.com")
    assert settings.public_url.scheme == "http"


def test_docmost_url_rejects_http_by_default() -> None:
    with pytest.raises(ValidationError, match="DOCMOST_ALLOW_INSECURE_HTTP"):
        Settings(public_url="https://mcp.example.com", docmost_url="http://docmost:3000")


def test_docmost_url_allows_http_with_flag() -> None:
    settings = Settings(
        public_url="https://mcp.example.com",
        docmost_url="http://docmost:3000",
        docmost_allow_insecure_http=True,
    )
    assert settings.docmost_url_is_insecure


def test_rejects_non_http_scheme() -> None:
    with pytest.raises(ValidationError):
        Settings(public_url="https://mcp.example.com", docmost_url="ftp://docs.example.com")
