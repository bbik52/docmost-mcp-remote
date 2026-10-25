from __future__ import annotations

from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.db.schema import metadata


async def test_migrations_match_schema(engine: AsyncEngine) -> None:
    def diff(connection: Any) -> list[Any]:
        return list(compare_metadata(MigrationContext.configure(connection), metadata))

    async with engine.connect() as connection:
        assert await connection.run_sync(diff) == []
