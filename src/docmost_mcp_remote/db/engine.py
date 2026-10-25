"""Database engine and migrations."""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
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


def _upgrade(url: str) -> None:
    command.upgrade(alembic_config(url), "head")


async def migrate(url: str) -> None:
    """Bring the schema to the newest version. Safe to run on every start."""
    await asyncio.to_thread(_upgrade, url)
