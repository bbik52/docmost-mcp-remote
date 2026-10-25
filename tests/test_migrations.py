from __future__ import annotations

import asyncio
import subprocess
import sys
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.db.engine import (
    SchemaError,
    alembic_config,
    create_engine,
    head_revision,
    migrate,
)
from docmost_mcp_remote.db.schema import metadata


async def test_migrations_match_schema(engine: AsyncEngine) -> None:
    def diff(connection: Any) -> list[Any]:
        return list(compare_metadata(MigrationContext.configure(connection), metadata))

    async with engine.connect() as connection:
        assert await connection.run_sync(diff) == []


def _sql(url: str, statement: str) -> list[Any]:
    async def run() -> list[Any]:
        engine = create_engine(url)
        try:
            async with engine.begin() as connection:
                result = await connection.execute(text(statement))
                return list(result.all()) if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _revision(url: str) -> str | None:
    rows = _sql(url, "SELECT version_num FROM alembic_version")
    return rows[0][0] if rows else None


@pytest.fixture
def database(migrated_database: str) -> Iterator[str]:
    yield migrated_database
    # Every test leaves the tables at head; put back a version row a test faked.
    if _revision(migrated_database) != head_revision():
        _sql(migrated_database, "DELETE FROM alembic_version")
        command.stamp(alembic_config(migrated_database), "head")


def test_every_revision_upgrades_to_head_with_data(database: str) -> None:
    config = alembic_config(database)
    revisions = [
        revision.revision
        for revision in reversed(list(ScriptDirectory.from_config(config).walk_revisions()))
    ]
    command.downgrade(config, "base")
    for revision in revisions:
        command.upgrade(config, revision)
        if revision == revisions[0]:
            # Rows written by the oldest schema must survive every later migration.
            _sql(
                database,
                "INSERT INTO members (id, docmost_user_id, email) "
                "VALUES ('00000000-0000-0000-0000-000000000001', 'u1', 'anna@example.com')",
            )
    assert _revision(database) == head_revision()
    assert _sql(database, "SELECT email FROM members") == [("anna@example.com",)]
    _sql(database, "TRUNCATE members CASCADE")


def test_concurrent_starts_wait_for_each_other(database: str) -> None:
    # Alembic keeps global state, so the concurrent servers have to be separate processes.
    command.downgrade(alembic_config(database), "base")
    code = (
        "import asyncio, sys; from docmost_mcp_remote.db.engine import migrate; "
        "asyncio.run(migrate(sys.argv[1]))"
    )
    processes = [
        subprocess.Popen([sys.executable, "-c", code, database])  # noqa: S603
        for _ in range(3)
    ]
    assert [process.wait(timeout=60) for process in processes] == [0, 0, 0]
    assert _revision(database) == head_revision()


def test_schema_from_a_newer_version_is_refused(database: str) -> None:
    _sql(database, "UPDATE alembic_version SET version_num = '9999'")
    with pytest.raises(SchemaError, match="newer version"):
        asyncio.run(migrate(database))
    assert _revision(database) == "9999"
