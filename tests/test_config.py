from __future__ import annotations

import pytest
from pydantic import ValidationError

from docmost_mcp_remote.config import Settings
from tests.conftest import SECRET, make_settings

REQUIRED = {
    "PUBLIC_URL": "https://mcp.example.com",
    "DOCMOST_URL": "https://docs.example.com",
    "DATABASE_URL": "postgresql://u:p@db/x",
    "SECRET_KEY": SECRET,
}


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("ALLOWED_EMAILS", " Anna@Example.com, bob@example.com ,")

    settings = Settings()

    assert settings.public_url.host == "mcp.example.com"
    assert settings.port == 9000
    assert settings.allowed_emails == {"anna@example.com", "bob@example.com"}
    assert settings.relogin_mode == "ask"
    assert not settings.docmost_url_is_insecure
    assert SECRET not in repr(settings)
    assert "u:p@db" not in repr(settings)


@pytest.mark.parametrize("missing", list(REQUIRED))
def test_required_values(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    for name, value in REQUIRED.items():
        if name != missing:
            monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match=missing.lower()):
        Settings()


def test_public_url_rejects_http() -> None:
    with pytest.raises(ValidationError, match="PUBLIC_URL must use https"):
        make_settings(public_url="http://mcp.example.com")


@pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1:8000"])
def test_public_url_allows_http_on_localhost(url: str) -> None:
    assert make_settings(public_url=url).public_url.scheme == "http"


def test_docmost_url_rejects_http_by_default() -> None:
    with pytest.raises(ValidationError, match="DOCMOST_ALLOW_INSECURE_HTTP"):
        make_settings(docmost_url="http://docmost:3000")


def test_docmost_url_allows_http_with_flag() -> None:
    settings = make_settings(docmost_url="http://docmost:3000", docmost_allow_insecure_http=True)
    assert settings.docmost_url_is_insecure


def test_rejects_non_http_scheme() -> None:
    with pytest.raises(ValidationError):
        make_settings(docmost_url="ftp://docs.example.com")


def test_short_secret_key() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        make_settings(secret_key="short")


def test_database_must_be_postgres() -> None:
    with pytest.raises(ValidationError, match="postgresql"):
        make_settings(database_url="sqlite:///x.db")


def test_email_allowed() -> None:
    assert make_settings().email_allowed("anyone@example.com")
    restricted = make_settings(allowed_emails="anna@example.com")
    assert restricted.email_allowed(" ANNA@example.com ")
    assert not restricted.email_allowed("bob@example.com")


def test_empty_previous_key_is_none() -> None:
    assert make_settings(secret_key_previous="").secret_key_previous is None


def test_allowed_spaces() -> None:
    assert make_settings(allowed_spaces=" general, 01a17251 ,").allowed_spaces == {
        "general",
        "01a17251",
    }
