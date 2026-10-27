"""Queries on the server's own tables."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.crypto import hash_token, new_token
from docmost_mcp_remote.db.schema import docmost_sessions, grants, members, tokens

#: How often ``last_used_at`` of a grant is written at most.
_LAST_USED_RESOLUTION = timedelta(minutes=5)


def now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Member:
    id: uuid.UUID
    docmost_user_id: str
    email: str
    name: str | None
    #: Web sessions signed in before this time are no longer accepted.
    web_sessions_after: datetime | None = None


@dataclass(frozen=True, slots=True)
class StoredSession:
    token_ciphertext: bytes
    password_ciphertext: bytes | None
    expired: bool


@dataclass(frozen=True, slots=True)
class GrantInfo:
    id: uuid.UUID
    kind: str
    name: str
    scopes: frozenset[str]
    created_at: datetime
    last_used_at: datetime | None
    token_hint: str | None
    #: When a personal token stops working; None when it does not expire.
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TokenOwner:
    """Who a presented bearer token belongs to."""

    member_id: uuid.UUID
    grant_id: uuid.UUID
    scopes: frozenset[str]
    expires_at: datetime | None
    #: ``personal`` or ``access`` (OAuth).
    kind: str
    #: The resource an OAuth access token is bound to.
    resource: str | None
    #: The OAuth client of the grant; None for personal tokens.
    client_id: str | None
    #: The member's email, for ``ALLOWED_EMAILS``.
    email: str


def _scopes(text: str) -> frozenset[str]:
    return frozenset(text.split())


class Store:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def upsert_member(self, docmost_user_id: str, email: str, name: str | None) -> Member:
        statement = (
            insert(members)
            .values(
                id=uuid.uuid4(),
                docmost_user_id=docmost_user_id,
                email=email,
                name=name,
                last_login_at=now(),
            )
            .on_conflict_do_update(
                index_elements=[members.c.docmost_user_id],
                set_={"email": email, "name": name, "last_login_at": now()},
            )
            .returning(members.c.id, members.c.disabled_at)
        )
        async with self.engine.begin() as connection:
            row = (await connection.execute(statement)).one()
        return Member(id=row.id, docmost_user_id=docmost_user_id, email=email, name=name)

    async def member_disabled(self, member_id: uuid.UUID) -> bool:
        async with self.engine.connect() as connection:
            disabled = await connection.scalar(
                select(members.c.disabled_at).where(members.c.id == member_id)
            )
        return disabled is not None

    async def get_member(self, member_id: uuid.UUID) -> Member | None:
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(select(members).where(members.c.id == member_id))
            ).one_or_none()
        if row is None:
            return None
        return Member(
            id=row.id,
            docmost_user_id=row.docmost_user_id,
            email=row.email,
            name=row.name,
            web_sessions_after=row.web_sessions_after,
        )

    async def end_web_sessions(self, member_id: uuid.UUID) -> None:
        """Sign the member out of the account pages in every browser."""
        async with self.engine.begin() as connection:
            await connection.execute(
                update(members).where(members.c.id == member_id).values(web_sessions_after=now())
            )

    async def save_session(
        self, member_id: uuid.UUID, token_ciphertext: bytes, password_ciphertext: bytes | None
    ) -> None:
        values = {
            "token_ciphertext": token_ciphertext,
            "password_ciphertext": password_ciphertext,
            "expired_at": None,
            "updated_at": now(),
        }
        statement = (
            insert(docmost_sessions)
            .values(member_id=member_id, **values)
            .on_conflict_do_update(index_elements=[docmost_sessions.c.member_id], set_=values)
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)

    async def load_session(self, member_id: uuid.UUID) -> StoredSession | None:
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    select(docmost_sessions).where(docmost_sessions.c.member_id == member_id)
                )
            ).one_or_none()
        if row is None:
            return None
        return StoredSession(
            token_ciphertext=row.token_ciphertext,
            password_ciphertext=row.password_ciphertext,
            expired=row.expired_at is not None,
        )

    async def expire_session(self, member_id: uuid.UUID) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                update(docmost_sessions)
                .where(docmost_sessions.c.member_id == member_id)
                .values(expired_at=now())
            )

    async def create_personal_token(
        self,
        member_id: uuid.UUID,
        name: str,
        scopes: frozenset[str],
        expires_at: datetime | None = None,
    ) -> tuple[uuid.UUID, str]:
        """Create a grant with one bearer token. The token is returned once, never stored."""
        grant_id = uuid.uuid4()
        token = new_token()
        async with self.engine.begin() as connection:
            await connection.execute(
                grants.insert().values(
                    id=grant_id,
                    member_id=member_id,
                    kind="personal",
                    name=name,
                    scopes=" ".join(sorted(scopes)),
                )
            )
            await connection.execute(
                tokens.insert().values(
                    id=uuid.uuid4(),
                    grant_id=grant_id,
                    kind="personal",
                    token_hash=hash_token(token),
                    hint=token[:10],
                    expires_at=expires_at,
                )
            )
        return grant_id, token

    async def list_grants(self, member_id: uuid.UUID) -> list[GrantInfo]:
        hint = (
            select(func.min(tokens.c.hint))
            .where(tokens.c.grant_id == grants.c.id)
            .scalar_subquery()
        )
        expires = (
            select(func.max(tokens.c.expires_at))
            .where(and_(tokens.c.grant_id == grants.c.id, tokens.c.kind == "personal"))
            .scalar_subquery()
        )
        query = (
            select(grants, hint.label("hint"), expires.label("expires"))
            .where(and_(grants.c.member_id == member_id, grants.c.revoked_at.is_(None)))
            .order_by(grants.c.created_at.desc())
        )
        async with self.engine.connect() as connection:
            rows = (await connection.execute(query)).all()
        return [
            GrantInfo(
                id=row.id,
                kind=row.kind,
                name=row.name,
                scopes=_scopes(row.scopes),
                created_at=row.created_at,
                last_used_at=row.last_used_at,
                token_hint=row.hint,
                expires_at=row.expires,
            )
            for row in rows
        ]

    async def revoke_grant(self, member_id: uuid.UUID, grant_id: uuid.UUID) -> bool:
        """Revoke one of the member's grants. False when it is not theirs or already revoked."""
        async with self.engine.begin() as connection:
            result = await connection.execute(
                update(grants)
                .where(
                    and_(
                        grants.c.id == grant_id,
                        grants.c.member_id == member_id,
                        grants.c.revoked_at.is_(None),
                    )
                )
                .values(revoked_at=now())
            )
        return bool(result.rowcount)

    async def grant_active(self, member_id: uuid.UUID, grant_id: uuid.UUID) -> bool:
        """The member's grant exists and is not revoked."""
        async with self.engine.connect() as connection:
            found = await connection.scalar(
                select(grants.c.id).where(
                    and_(
                        grants.c.id == grant_id,
                        grants.c.member_id == member_id,
                        grants.c.revoked_at.is_(None),
                    )
                )
            )
        return found is not None

    async def find_token(self, token: str) -> TokenOwner | None:
        """Resolve a presented bearer token; None when unknown, revoked or expired."""
        query = (
            select(
                grants.c.member_id,
                grants.c.id.label("grant_id"),
                grants.c.scopes,
                grants.c.last_used_at,
                grants.c.client_id,
                members.c.email,
                tokens.c.kind,
                tokens.c.expires_at,
                tokens.c.resource,
                tokens.c.scopes.label("token_scopes"),
            )
            .select_from(
                tokens.join(grants, tokens.c.grant_id == grants.c.id).join(
                    members, grants.c.member_id == members.c.id
                )
            )
            .where(
                and_(
                    tokens.c.token_hash == hash_token(token),
                    tokens.c.kind.in_(("personal", "access")),
                    tokens.c.revoked_at.is_(None),
                    grants.c.revoked_at.is_(None),
                    members.c.disabled_at.is_(None),
                )
            )
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).one_or_none()
        if row is None:
            return None
        current = now()
        if row.expires_at is not None and row.expires_at <= current:
            return None
        if row.last_used_at is None or current - row.last_used_at > _LAST_USED_RESOLUTION:
            async with self.engine.begin() as connection:
                await connection.execute(
                    update(grants).where(grants.c.id == row.grant_id).values(last_used_at=current)
                )
        scopes = _scopes(row.scopes)
        if row.token_scopes is not None:
            scopes &= _scopes(row.token_scopes)
        return TokenOwner(
            member_id=row.member_id,
            grant_id=row.grant_id,
            scopes=scopes,
            expires_at=row.expires_at,
            kind=row.kind,
            resource=row.resource,
            client_id=row.client_id,
            email=row.email,
        )
