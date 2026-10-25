from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.db.engine import create_engine

_ENV_VARS = (
    "PUBLIC_URL",
    "DOCMOST_URL",
    "DOCMOST_ALLOW_INSECURE_HTTP",
    "DOCMOST_TIMEOUT_SECONDS",
    "DOCMOST_MAX_RESPONSE_BYTES",
    "DATABASE_URL",
    "SECRET_KEY",
    "SECRET_KEY_PREVIOUS",
    "ALLOWED_EMAILS",
    "RELOGIN_MODE",
    "HOST",
    "PORT",
    "LOG_LEVEL",
)

#: Postgres for tests that need one, e.g. postgresql://test:test@localhost:5433/test.
DATABASE_TEST_URL = os.environ.get("DATABASE_TEST_URL", "")
SECRET = "test-secret-key-0123456789abcdef-0123"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep tests independent of the developer's environment and any local .env file."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "public_url": "https://mcp.example.com",
        "docmost_url": "https://docs.example.com",
        "database_url": DATABASE_TEST_URL or "postgresql://unused@localhost/unused",
        "secret_key": SECRET,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture(scope="session")
def migrated_database() -> str:
    if not DATABASE_TEST_URL:
        pytest.skip("DATABASE_TEST_URL is not set")
    import asyncio

    from docmost_mcp_remote.db.engine import migrate

    async def reset() -> None:
        engine = create_engine(DATABASE_TEST_URL)
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
        await engine.dispose()
        await migrate(DATABASE_TEST_URL)

    asyncio.run(reset())
    return DATABASE_TEST_URL


@pytest.fixture
async def engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(migrated_database)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE members, docmost_sessions, grants, tokens, oauth_clients, "
                "oauth_requests, oauth_codes, snapshots RESTART IDENTITY CASCADE"
            )
        )
    try:
        yield engine
    finally:
        await engine.dispose()
