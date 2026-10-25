"""Queries for the audit log and the admin command line."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.crypto import Cipher
from docmost_mcp_remote.db.schema import (
    audit_log,
    docmost_sessions,
    grants,
    members,
    snapshots,
    tokens,
)
from docmost_mcp_remote.db.snapshot_store import snapshot_context
from docmost_mcp_remote.db.store import now


@dataclass(frozen=True, slots=True)
class AuditEntry:
    created_at: datetime
    email: str | None
    tool: str
    page_id: str | None
    space_id: str | None
    outcome: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class MemberRow:
    id: uuid.UUID
    email: str
    name: str | None
    created_at: datetime
    last_login_at: datetime | None
    disabled: bool
    active_grants: int


@dataclass(frozen=True, slots=True)
class GrantRow:
    id: uuid.UUID
    kind: str
    name: str
    scopes: str
    created_at: datetime
    last_used_at: datetime | None


class AuditStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def record(
        self,
        *,
        member_id: uuid.UUID | None,
        grant_id: uuid.UUID | None,
        tool: str,
        page_id: str | None,
        space_id: str | None,
        outcome: str,
        duration_ms: int,
    ) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                audit_log.insert().values(
                    member_id=member_id,
                    grant_id=grant_id,
                    tool=tool[:64],
                    page_id=page_id[:64] if page_id else None,
                    space_id=space_id[:64] if space_id else None,
                    outcome=outcome,
                    duration_ms=duration_ms,
                )
            )

    async def entries(self, *, email: str | None = None, limit: int = 50) -> list[AuditEntry]:
        query = (
            select(
                audit_log.c.created_at,
                members.c.email,
                audit_log.c.tool,
                audit_log.c.page_id,
                audit_log.c.space_id,
                audit_log.c.outcome,
                audit_log.c.duration_ms,
            )
            .select_from(audit_log.outerjoin(members, audit_log.c.member_id == members.c.id))
            .order_by(audit_log.c.id.desc())
            .limit(limit)
        )
        if email:
            query = query.where(func.lower(members.c.email) == email.strip().lower())
        async with self.engine.connect() as connection:
            rows = (await connection.execute(query)).all()
        return [AuditEntry(**row._mapping) for row in rows]

    async def cleanup(self, retention: timedelta) -> int:
        async with self.engine.begin() as connection:
            result = await connection.execute(
                delete(audit_log).where(audit_log.c.created_at < now() - retention)
            )
        return int(result.rowcount or 0)


class AdminStore:
    """What the ``admin`` command line does. Every change is limited to one member or grant."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def members(self) -> list[MemberRow]:
        active = (
            select(func.count())
            .where(and_(grants.c.member_id == members.c.id, grants.c.revoked_at.is_(None)))
            .scalar_subquery()
        )
        query = select(members, active.label("active_grants")).order_by(members.c.email)
        async with self.engine.connect() as connection:
            rows = (await connection.execute(query)).all()
        return [
            MemberRow(
                id=row.id,
                email=row.email,
                name=row.name,
                created_at=row.created_at,
                last_login_at=row.last_login_at,
                disabled=row.disabled_at is not None,
                active_grants=row.active_grants,
            )
            for row in rows
        ]

    async def member_id(self, email: str) -> uuid.UUID | None:
        async with self.engine.connect() as connection:
            return await connection.scalar(
                select(members.c.id).where(func.lower(members.c.email) == email.strip().lower())
            )

    async def grants(self, member_id: uuid.UUID) -> list[GrantRow]:
        query = (
            select(grants)
            .where(and_(grants.c.member_id == member_id, grants.c.revoked_at.is_(None)))
            .order_by(grants.c.created_at.desc())
        )
        async with self.engine.connect() as connection:
            rows = (await connection.execute(query)).all()
        return [
            GrantRow(
                id=row.id,
                kind=row.kind,
                name=row.name,
                scopes=row.scopes,
                created_at=row.created_at,
                last_used_at=row.last_used_at,
            )
            for row in rows
        ]

    async def revoke_grant(self, grant_id: uuid.UUID) -> bool:
        async with self.engine.begin() as connection:
            result = await connection.execute(
                update(grants)
                .where(and_(grants.c.id == grant_id, grants.c.revoked_at.is_(None)))
                .values(revoked_at=now())
            )
            await connection.execute(
                update(tokens)
                .where(and_(tokens.c.grant_id == grant_id, tokens.c.revoked_at.is_(None)))
                .values(revoked_at=now())
            )
        return bool(result.rowcount)

    async def revoke_member(self, member_id: uuid.UUID) -> int:
        """Revoke every grant of a member and drop their Docmost session."""
        async with self.engine.begin() as connection:
            result = await connection.execute(
                update(grants)
                .where(and_(grants.c.member_id == member_id, grants.c.revoked_at.is_(None)))
                .values(revoked_at=now())
            )
            await connection.execute(
                update(tokens)
                .where(
                    and_(
                        tokens.c.grant_id.in_(
                            select(grants.c.id).where(grants.c.member_id == member_id)
                        ),
                        tokens.c.revoked_at.is_(None),
                    )
                )
                .values(revoked_at=now())
            )
            await connection.execute(
                delete(docmost_sessions).where(docmost_sessions.c.member_id == member_id)
            )
        return int(result.rowcount or 0)

    async def set_disabled(self, member_id: uuid.UUID, disabled: bool) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                update(members)
                .where(members.c.id == member_id)
                .values(disabled_at=now() if disabled else None)
            )

    async def rotate_key(self, cipher: Cipher) -> tuple[int, int]:
        """Re-encrypt stored sessions and snapshots that still use the previous key."""
        sessions_done = snapshots_done = 0
        async with self.engine.begin() as connection:
            rows = (await connection.execute(select(docmost_sessions))).all()
            for row in rows:
                context = str(row.member_id)
                values: dict[str, bytes] = {}
                if cipher.needs_rotation(row.token_ciphertext):
                    values["token_ciphertext"] = cipher.encrypt(
                        cipher.decrypt(row.token_ciphertext, context=context), context=context
                    )
                if row.password_ciphertext and cipher.needs_rotation(row.password_ciphertext):
                    values["password_ciphertext"] = cipher.encrypt(
                        cipher.decrypt(row.password_ciphertext, context=context), context=context
                    )
                if values:
                    await connection.execute(
                        update(docmost_sessions)
                        .where(docmost_sessions.c.member_id == row.member_id)
                        .values(**values)
                    )
                    sessions_done += 1
            rows = (
                await connection.execute(
                    select(snapshots.c.id, snapshots.c.member_id, snapshots.c.ciphertext)
                )
            ).all()
            for row in rows:
                if not cipher.needs_rotation(row.ciphertext):
                    continue
                context = snapshot_context(row.id, row.member_id)
                await connection.execute(
                    update(snapshots)
                    .where(snapshots.c.id == row.id)
                    .values(
                        ciphertext=cipher.encrypt(
                            cipher.decrypt(row.ciphertext, context=context), context=context
                        )
                    )
                )
                snapshots_done += 1
        return sessions_done, snapshots_done
