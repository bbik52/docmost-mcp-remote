"""Upload links and the files sent to them, until they are in Docmost or expire."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.crypto import Cipher, hash_token
from docmost_mcp_remote.db.schema import grants, upload_files, upload_links
from docmost_mcp_remote.db.store import now

LinkState = Literal["open", "adding", "done"]


class UploadLimitError(Exception):
    """The file does not fit in what the link still accepts."""


@dataclass(frozen=True, slots=True)
class UploadLink:
    id: uuid.UUID
    member_id: uuid.UUID
    page_id: str
    #: Page title and link, where files go; see ``UploadStore.create``.
    details: dict[str, Any]
    state: LinkState
    outcome: dict[str, Any] | None
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class UploadFile:
    id: uuid.UUID
    file_name: str
    mime_type: str
    size: int
    position: int
    attachment_id: str | None


def _details_context(link_id: uuid.UUID, member_id: uuid.UUID) -> str:
    return f"upload-link:{link_id}:{member_id}"


def _file_context(link_id: uuid.UUID, file_id: uuid.UUID) -> str:
    return f"upload-file:{link_id}:{file_id}"


_FILE_COLUMNS = (
    upload_files.c.id,
    upload_files.c.file_name,
    upload_files.c.mime_type,
    upload_files.c.size,
    upload_files.c.position,
    upload_files.c.attachment_id,
)


class UploadStore:
    def __init__(self, engine: AsyncEngine, cipher: Cipher) -> None:
        self.engine = engine
        self._cipher = cipher

    async def create(
        self,
        *,
        member_id: uuid.UUID,
        grant_id: uuid.UUID,
        token: str,
        page_id: str,
        details: dict[str, Any],
        lifetime: timedelta,
    ) -> UploadLink:
        link_id = uuid.uuid4()
        created = now()
        sealed = self._cipher.encrypt(
            json.dumps(details), context=_details_context(link_id, member_id)
        )
        async with self.engine.begin() as connection:
            await connection.execute(
                upload_links.insert().values(
                    id=link_id,
                    member_id=member_id,
                    grant_id=grant_id,
                    token_hash=hash_token(token),
                    page_id=page_id,
                    details=sealed,
                    state="open",
                    created_at=created,
                    expires_at=created + lifetime,
                )
            )
        return UploadLink(
            link_id, member_id, page_id, details, "open", None, created, created + lifetime
        )

    def _link(self, row: Any) -> UploadLink:
        details = json.loads(
            self._cipher.decrypt(row.details, context=_details_context(row.id, row.member_id))
        )
        return UploadLink(
            id=row.id,
            member_id=row.member_id,
            page_id=row.page_id,
            details=details,
            state=row.state,
            outcome=json.loads(row.outcome) if row.outcome else None,
            created_at=row.created_at,
            expires_at=row.expires_at,
        )

    async def by_token(self, token: str) -> UploadLink | None:
        """The link a token opens; None when unknown, expired or its grant was revoked."""
        query = (
            select(upload_links)
            .select_from(upload_links.join(grants, upload_links.c.grant_id == grants.c.id))
            .where(
                and_(
                    upload_links.c.token_hash == hash_token(token),
                    upload_links.c.expires_at > now(),
                    grants.c.revoked_at.is_(None),
                )
            )
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).one_or_none()
        return self._link(row) if row else None

    async def by_id(self, member_id: uuid.UUID, link_id: uuid.UUID) -> UploadLink | None:
        """One of the member's links; None when not theirs or expired."""
        query = select(upload_links).where(
            and_(
                upload_links.c.id == link_id,
                upload_links.c.member_id == member_id,
                upload_links.c.expires_at > now(),
            )
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).one_or_none()
        return self._link(row) if row else None

    async def files(self, link_id: uuid.UUID) -> list[UploadFile]:
        query = (
            select(*_FILE_COLUMNS)
            .where(upload_files.c.link_id == link_id)
            .order_by(upload_files.c.position)
        )
        async with self.engine.connect() as connection:
            rows = (await connection.execute(query)).all()
        return [UploadFile(**row._mapping) for row in rows]

    async def add_file(
        self,
        link: UploadLink,
        *,
        file_name: str,
        mime_type: str,
        content: bytes,
        max_bytes: int,
        max_files: int,
    ) -> UploadFile:
        """Keep a file for the link, if the link is open and it fits in its limits."""
        file_id = uuid.uuid4()
        sealed = self._cipher.encrypt_bytes(content, context=_file_context(link.id, file_id))
        async with self.engine.begin() as connection:
            # The row lock makes concurrent uploads to one link take turns.
            state = (
                await connection.execute(
                    select(upload_links.c.state)
                    .where(upload_links.c.id == link.id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if state != "open":
                raise UploadLimitError("This link no longer accepts files.")
            count, used, last = (
                await connection.execute(
                    select(
                        func.count(),
                        func.coalesce(func.sum(upload_files.c.size), 0),
                        func.coalesce(func.max(upload_files.c.position), -1),
                    ).where(upload_files.c.link_id == link.id)
                )
            ).one()
            if count >= max_files:
                raise UploadLimitError(f"A link takes at most {max_files} files.")
            if used + len(content) > max_bytes:
                raise UploadLimitError(
                    f"The files of one link may be {max_bytes // (1024 * 1024)} MB in total."
                )
            position = int(last) + 1
            await connection.execute(
                upload_files.insert().values(
                    id=file_id,
                    link_id=link.id,
                    file_name=file_name,
                    mime_type=mime_type,
                    size=len(content),
                    position=position,
                    ciphertext=sealed,
                )
            )
        return UploadFile(file_id, file_name, mime_type, len(content), position, None)

    async def content(self, link_id: uuid.UUID, file_id: uuid.UUID) -> bytes | None:
        query = select(upload_files.c.ciphertext).where(
            and_(upload_files.c.link_id == link_id, upload_files.c.id == file_id)
        )
        async with self.engine.connect() as connection:
            sealed = (await connection.execute(query)).scalar_one_or_none()
        if sealed is None:
            return None
        return self._cipher.decrypt_bytes(sealed, context=_file_context(link_id, file_id))

    async def remove_file(self, link_id: uuid.UUID, file_id: uuid.UUID) -> bool:
        """Drop a file that is not in Docmost yet, while the link is open."""
        async with self.engine.begin() as connection:
            state = (
                await connection.execute(
                    select(upload_links.c.state)
                    .where(upload_links.c.id == link_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if state != "open":
                return False
            result = await connection.execute(
                delete(upload_files).where(
                    and_(
                        upload_files.c.link_id == link_id,
                        upload_files.c.id == file_id,
                        upload_files.c.attachment_id.is_(None),
                    )
                )
            )
        return bool(result.rowcount)

    async def uploaded(self, link_id: uuid.UUID, file_id: uuid.UUID, attachment_id: str) -> None:
        """The file is in Docmost now; its content is no longer kept here."""
        async with self.engine.begin() as connection:
            await connection.execute(
                update(upload_files)
                .where(and_(upload_files.c.link_id == link_id, upload_files.c.id == file_id))
                .values(attachment_id=attachment_id, ciphertext=None)
            )

    async def start_adding(self, link_id: uuid.UUID) -> bool:
        """Claim an open link for adding its files; False when it is not open."""
        async with self.engine.begin() as connection:
            result = await connection.execute(
                update(upload_links)
                .where(and_(upload_links.c.id == link_id, upload_links.c.state == "open"))
                .values(state="adding")
            )
        return bool(result.rowcount)

    async def finish(self, link_id: uuid.UUID, state: LinkState, outcome: dict[str, Any]) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                update(upload_links)
                .where(upload_links.c.id == link_id)
                .values(state=state, outcome=json.dumps(outcome))
            )

    async def cleanup(self) -> int:
        """Delete expired links with their files: what was not added to a page is gone."""
        async with self.engine.begin() as connection:
            result = await connection.execute(
                delete(upload_links).where(upload_links.c.expires_at <= now())
            )
        return int(result.rowcount or 0)
