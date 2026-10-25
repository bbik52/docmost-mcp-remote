from __future__ import annotations

from pathlib import Path

import pytest

from docmost_mcp_remote.config import Settings

_ENV_VARS = (
    "PUBLIC_URL",
    "DOCMOST_URL",
    "DOCMOST_ALLOW_INSECURE_HTTP",
    "DATABASE_URL",
    "HOST",
    "PORT",
    "LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep tests independent of the developer's environment and any local .env file."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        public_url="https://mcp.example.com",
        docmost_url="https://docs.example.com",
    )
