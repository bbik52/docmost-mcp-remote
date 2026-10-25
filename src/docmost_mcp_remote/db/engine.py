"""Database engine and migrations."""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

_MIGRATIONS = Path(__file__).parent / "migrations"


def async_url(url: str) -> str:
    """Point a plain ``postgresql://`` URL at the asyncpg driver."""
    scheme, rest = url.split("://", 1)
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    return f"{scheme}://{rest}"


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(async_url(url), pool_pre_ping=True, pool_size=5, max_overflow=5)


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS))
    config.attributes["database_url"] = async_url(url)
    return config


class SchemaError(RuntimeError):
    """The database schema cannot be used by this version of the server."""


def check_known_revision(connection: Connection, script: ScriptDirectory) -> str | None:
    """The current revision, or SchemaError if a newer server version created it."""
    current = MigrationContext.configure(connection).get_current_revision()
    known = {revision.revision for revision in script.walk_revisions()}
    if current is not None and current not in known:
        raise SchemaError(
            f"The database schema is at revision {current}, which this version of the server "
            "does not know: a newer version has upgraded it. Run that newer version, or restore "
            "the database backup taken before the upgrade."
        )
    return current


def _upgrade(url: str) -> None:
    command.upgrade(alembic_config(url), "head")


async def migrate(url: str) -> None:
    """Bring the schema to the newest version. Safe to run on every start.

    Concurrent starts wait for each other on a Postgres advisory lock, and a
    schema created by a newer server version is refused with SchemaError
    instead of being touched.
    """
    await asyncio.to_thread(_upgrade, url)


def head_revision() -> str:
    head = ScriptDirectory.from_config(
        alembic_config("postgresql://unused/unused")
    ).get_current_head()
    if head is None:
        raise SchemaError("no migrations found")
    return head


async def current_revision(engine: AsyncEngine) -> str | None:
    async with engine.connect() as connection:
        return await connection.run_sync(
            lambda sync: MigrationContext.configure(sync).get_current_revision()
        )
