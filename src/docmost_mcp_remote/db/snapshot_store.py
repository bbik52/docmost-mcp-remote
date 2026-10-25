"""Snapshots: page bodies saved before the server changes them."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.crypto import Cipher
from docmost_mcp_remote.db.schema import snapshots
from docmost_mcp_remote.db.store import now


@dataclass(frozen=True, slots=True)
class SnapshotInfo:
    id: uuid.UUID
    page_id: str
    space_id: str
    reason: str
    content_chars: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Snapshot:
    info: SnapshotInfo
    title: str | None
    content: str


def _context(snapshot_id: uuid.UUID, member_id: uuid.UUID) -> str:
    return f"snapshot:{snapshot_id}:{member_id}"


class SnapshotStore:
    def __init__(self, engine: AsyncEngine, cipher: Cipher) -> None:
        self.engine = engine
        self._cipher = cipher

    async def save(
        self,
        *,
        member_id: uuid.UUID,
        page_id: str,
        space_id: str,
        title: str | None,
        content: str,
        reason: str,
    ) -> uuid.UUID:
        snapshot_id = uuid.uuid4()
        plaintext = json.dumps({"title": title, "content": content})
        async with self.engine.begin() as connection:
            await connection.execute(
                snapshots.insert().values(
                    id=snapshot_id,
                    member_id=member_id,
                    page_id=page_id,
                    space_id=space_id,
                    reason=reason,
                    ciphertext=self._cipher.encrypt(
                        plaintext, context=_context(snapshot_id, member_id)
                    ),
                    content_chars=len(content),
                )
            )
        return snapshot_id

    async def list(self, member_id: uuid.UUID, page_id: str, limit: int) -> list[SnapshotInfo]:
        """The member's own snapshots of a page, newest first."""
        query = (
            select(
                snapshots.c.id,
                snapshots.c.page_id,
                snapshots.c.space_id,
                snapshots.c.reason,
                snapshots.c.content_chars,
                snapshots.c.created_at,
            )
            .where(and_(snapshots.c.member_id == member_id, snapshots.c.page_id == page_id))
            .order_by(snapshots.c.created_at.desc())
            .limit(limit)
        )
        async with self.engine.connect() as connection:
            rows = (await connection.execute(query)).all()
        return [SnapshotInfo(**row._mapping) for row in rows]

    async def load(self, member_id: uuid.UUID, snapshot_id: uuid.UUID) -> Snapshot | None:
        """One of the member's snapshots with its content; None when not theirs or gone."""
        query = select(snapshots).where(
            and_(snapshots.c.id == snapshot_id, snapshots.c.member_id == member_id)
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).one_or_none()
        if row is None:
            return None
        data = json.loads(
            self._cipher.decrypt(row.ciphertext, context=_context(row.id, row.member_id))
        )
        info = SnapshotInfo(
            id=row.id,
            page_id=row.page_id,
            space_id=row.space_id,
            reason=row.reason,
            content_chars=row.content_chars,
            created_at=row.created_at,
        )
        return Snapshot(info=info, title=data.get("title"), content=data.get("content", ""))

    async def cleanup(self, retention: timedelta) -> int:
        async with self.engine.begin() as connection:
            result = await connection.execute(
                delete(snapshots).where(snapshots.c.created_at < now() - retention)
            )
        return int(result.rowcount or 0)
