"""Alembic environment: runs migrations over the async engine."""

from __future__ import annotations

import asyncio

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from docmost_mcp_remote.db.engine import check_known_revision
from docmost_mcp_remote.db.schema import metadata

config = context.config

#: Any constant works; it only has to be the same for every server process.
_MIGRATION_LOCK = 0x646D725F6D696772  # "dmr_migr"


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    with context.begin_transaction():
        # Held until the migration transaction ends, so a second server that starts at
        # the same time waits here and then finds the schema already up to date.
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _MIGRATION_LOCK})
        check_known_revision(connection, ScriptDirectory.from_config(config))
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(config.attributes["database_url"])
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


asyncio.run(_run_async())
