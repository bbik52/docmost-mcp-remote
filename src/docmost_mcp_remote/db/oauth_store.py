"""Queries for the OAuth authorization server."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.crypto import hash_token, new_token
from docmost_mcp_remote.db.schema import (
    grants,
    members,
    oauth_clients,
    oauth_codes,
    oauth_requests,
    tokens,
)
from docmost_mcp_remote.db.store import now

#: Registered clients that never got a grant are deleted after this time.
UNUSED_CLIENT_TTL = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class StoredCode:
    grant_id: uuid.UUID
    member_id: uuid.UUID
    client_id: str
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    scopes: frozenset[str]
    resource: str | None
    expires_at: datetime
    used: bool


@dataclass(frozen=True, slots=True)
class StoredToken:
    grant_id: uuid.UUID
    member_id: uuid.UUID
    client_id: str | None
    kind: str
    scopes: frozenset[str]
    resource: str | None
    expires_at: datetime | None
    replaced: bool


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


class OAuthStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    # Clients

    async def save_client(self, client_id: str, info_json: str) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                oauth_clients.insert().values(client_id=client_id, info=info_json)
            )

    async def load_client(self, client_id: str) -> str | None:
        async with self.engine.connect() as connection:
            return await connection.scalar(
                select(oauth_clients.c.info).where(oauth_clients.c.client_id == client_id)
            )

    async def count_clients(self) -> int:
        async with self.engine.connect() as connection:
            return int(
                await connection.scalar(select(func.count()).select_from(oauth_clients)) or 0
            )

    # Pending authorization requests

    async def save_request(self, client_id: str, params_json: str, ttl: timedelta) -> str:
        request_id = new_token()
        async with self.engine.begin() as connection:
            await connection.execute(
                oauth_requests.insert().values(
                    id_hash=hash_token(request_id),
                    client_id=client_id,
                    params=params_json,
                    expires_at=now() + ttl,
                )
            )
        return request_id

    async def load_request(self, request_id: str) -> tuple[str, str] | None:
        """Return (client_id, params JSON) of a pending request that has not expired."""
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    select(oauth_requests.c.client_id, oauth_requests.c.params).where(
                        and_(
                            oauth_requests.c.id_hash == hash_token(request_id),
                            oauth_requests.c.expires_at > now(),
                        )
                    )
                )
            ).one_or_none()
        return (row.client_id, row.params) if row else None

    async def delete_request(self, request_id: str) -> bool:
        async with self.engine.begin() as connection:
            result = await connection.execute(
                delete(oauth_requests).where(oauth_requests.c.id_hash == hash_token(request_id))
            )
        return bool(result.rowcount)

    # Grants and codes

    async def create_grant_with_code(
        self,
        *,
        member_id: uuid.UUID,
        client_id: str,
        client_name: str,
        scopes: frozenset[str],
        code_challenge: str,
        redirect_uri: str,
        redirect_uri_provided_explicitly: bool,
        resource: str | None,
        ttl: timedelta,
    ) -> str:
        grant_id = uuid.uuid4()
        code = new_token()
        async with self.engine.begin() as connection:
            await connection.execute(
                grants.insert().values(
                    id=grant_id,
                    member_id=member_id,
                    kind="oauth",
                    name=client_name[:200],
                    scopes=" ".join(sorted(scopes)),
                    client_id=client_id,
                )
            )
            await connection.execute(
                oauth_codes.insert().values(
                    code_hash=hash_token(code),
                    grant_id=grant_id,
                    client_id=client_id,
                    code_challenge=code_challenge,
                    redirect_uri=redirect_uri,
                    redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
                    scopes=" ".join(sorted(scopes)),
                    resource=resource,
                    expires_at=now() + ttl,
                )
            )
        return code

    async def load_code(self, code: str) -> StoredCode | None:
        query = (
            select(oauth_codes, grants.c.member_id)
            .select_from(oauth_codes.join(grants, oauth_codes.c.grant_id == grants.c.id))
            .where(and_(oauth_codes.c.code_hash == hash_token(code), grants.c.revoked_at.is_(None)))
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).one_or_none()
        if row is None:
            return None
        return StoredCode(
            grant_id=row.grant_id,
            member_id=row.member_id,
            client_id=row.client_id,
            code_challenge=row.code_challenge,
            redirect_uri=row.redirect_uri,
            redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
            scopes=frozenset(row.scopes.split()),
            resource=row.resource,
            expires_at=row.expires_at,
            used=row.used_at is not None,
        )

    async def use_code(self, code: str) -> bool:
        """Mark a code used; False when it was already used (a replay)."""
        async with self.engine.begin() as connection:
            result = await connection.execute(
                update(oauth_codes)
                .where(
                    and_(
                        oauth_codes.c.code_hash == hash_token(code), oauth_codes.c.used_at.is_(None)
                    )
                )
                .values(used_at=now())
            )
        return bool(result.rowcount)

    async def revoke_grant(self, grant_id: uuid.UUID) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                update(grants)
                .where(and_(grants.c.id == grant_id, grants.c.revoked_at.is_(None)))
                .values(revoked_at=now())
            )

    # Tokens

    async def issue_tokens(
        self,
        grant_id: uuid.UUID,
        *,
        scopes: frozenset[str] | None,
        resource: str | None,
        access_ttl: timedelta,
        refresh_ttl: timedelta,
    ) -> IssuedTokens:
        access, refresh = new_token(), new_token()
        current = now()
        access_expires, refresh_expires = current + access_ttl, current + refresh_ttl
        async with self.engine.begin() as connection:
            for kind, token, expires in (
                ("access", access, access_expires),
                ("refresh", refresh, refresh_expires),
            ):
                await connection.execute(
                    tokens.insert().values(
                        id=uuid.uuid4(),
                        grant_id=grant_id,
                        kind=kind,
                        token_hash=hash_token(token),
                        hint=token[:10],
                        expires_at=expires,
                        resource=resource,
                        scopes=" ".join(sorted(scopes)) if scopes is not None else None,
                    )
                )
        return IssuedTokens(access, refresh, access_expires, refresh_expires)

    async def load_token(self, token: str) -> StoredToken | None:
        """A token of a live grant and an enabled member; expiry is left to the caller."""
        query = (
            select(
                tokens.c.kind,
                tokens.c.expires_at,
                tokens.c.resource,
                tokens.c.revoked_at,
                tokens.c.replaced_at,
                tokens.c.scopes.label("token_scopes"),
                grants.c.id.label("grant_id"),
                grants.c.member_id,
                grants.c.client_id,
                grants.c.scopes,
            )
            .select_from(
                tokens.join(grants, tokens.c.grant_id == grants.c.id).join(
                    members, grants.c.member_id == members.c.id
                )
            )
            .where(
                and_(
                    tokens.c.token_hash == hash_token(token),
                    grants.c.revoked_at.is_(None),
                    members.c.disabled_at.is_(None),
                )
            )
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).one_or_none()
        if row is None or (row.revoked_at is not None and row.replaced_at is None):
            return None
        scopes = frozenset(row.scopes.split())
        if row.token_scopes is not None:
            scopes &= frozenset(row.token_scopes.split())
        return StoredToken(
            grant_id=row.grant_id,
            member_id=row.member_id,
            client_id=row.client_id,
            kind=row.kind,
            scopes=scopes,
            resource=row.resource,
            expires_at=row.expires_at,
            replaced=row.replaced_at is not None,
        )

    async def replace_refresh_token(self, token: str) -> bool:
        """Retire a refresh token after use; False when another request already did."""
        async with self.engine.begin() as connection:
            result = await connection.execute(
                update(tokens)
                .where(
                    and_(tokens.c.token_hash == hash_token(token), tokens.c.replaced_at.is_(None))
                )
                .values(replaced_at=now(), revoked_at=now())
            )
        return bool(result.rowcount)

    async def revoke_grant_tokens(self, grant_id: uuid.UUID) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                update(tokens)
                .where(and_(tokens.c.grant_id == grant_id, tokens.c.revoked_at.is_(None)))
                .values(revoked_at=now())
            )

    async def cleanup(self) -> None:
        """Delete expired requests, codes and tokens, and clients that were never used."""
        current = now()
        async with self.engine.begin() as connection:
            await connection.execute(
                delete(oauth_clients).where(
                    and_(
                        oauth_clients.c.created_at < current - UNUSED_CLIENT_TTL,
                        ~select(grants.c.id)
                        .where(grants.c.client_id == oauth_clients.c.client_id)
                        .exists(),
                    )
                )
            )
            await connection.execute(
                delete(oauth_requests).where(oauth_requests.c.expires_at < current)
            )
            await connection.execute(
                delete(oauth_codes).where(oauth_codes.c.expires_at < current - timedelta(days=1))
            )
            await connection.execute(
                delete(tokens).where(
                    and_(
                        tokens.c.expires_at.is_not(None),
                        tokens.c.expires_at < current - timedelta(days=1),
                    )
                )
            )
