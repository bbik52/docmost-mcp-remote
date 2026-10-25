"""Table definitions (SQLAlchemy Core). Migrations in ``migrations/`` create them."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def _now() -> Column[datetime]:
    return Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now())


#: A person who signed in with their Docmost account.
members = Table(
    "members",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("docmost_user_id", String(64), nullable=False, unique=True),
    Column("email", String(320), nullable=False),
    Column("name", Text),
    _now(),
    Column("last_login_at", DateTime(timezone=True)),
    Column("disabled_at", DateTime(timezone=True)),
)

#: The member's Docmost session, encrypted. One row per member.
docmost_sessions = Table(
    "docmost_sessions",
    metadata,
    Column(
        "member_id",
        UUID(as_uuid=True),
        ForeignKey("members.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("token_ciphertext", LargeBinary, nullable=False),
    #: Only set when RELOGIN_MODE=stored_password.
    Column("password_ciphertext", LargeBinary),
    Column("expired_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

#: Permission a member gave one client (a personal token or, later, an OAuth client).
grants = Table(
    "grants",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "member_id",
        UUID(as_uuid=True),
        ForeignKey("members.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("kind", String(16), nullable=False),
    Column("name", String(200), nullable=False),
    #: Space-separated scopes: read, write, delete.
    Column("scopes", String(100), nullable=False),
    Column("client_id", String(200)),
    _now(),
    Column("last_used_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
)

#: Bearer tokens, stored as SHA-256 hashes.
tokens = Table(
    "tokens",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "grant_id",
        UUID(as_uuid=True),
        ForeignKey("grants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("kind", String(16), nullable=False),
    Column("token_hash", LargeBinary, nullable=False, unique=True),
    #: First characters of the token, shown so members can tell tokens apart.
    Column("hint", String(16), nullable=False),
    _now(),
    Column("expires_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
)

Index("ix_members_email", members.c.email)
