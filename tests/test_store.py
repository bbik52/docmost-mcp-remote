from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.crypto import hash_token
from docmost_mcp_remote.db.schema import members, tokens
from docmost_mcp_remote.db.store import Store, now


async def test_upsert_member_keeps_id(engine: AsyncEngine) -> None:
    store = Store(engine)
    first = await store.upsert_member("d1", "a@example.com", "A")
    second = await store.upsert_member("d1", "new@example.com", "A2")

    assert first.id == second.id
    stored = await store.get_member(first.id)
    assert stored is not None
    assert stored.email == "new@example.com"


async def test_sessions(engine: AsyncEngine) -> None:
    store = Store(engine)
    member = await store.upsert_member("d1", "a@example.com", None)
    assert await store.load_session(member.id) is None

    await store.save_session(member.id, b"token", None)
    session = await store.load_session(member.id)
    assert session is not None
    assert session.token_ciphertext == b"token"
    assert not session.expired

    await store.expire_session(member.id)
    session = await store.load_session(member.id)
    assert session is not None
    assert session.expired

    await store.save_session(member.id, b"token2", b"pw")
    session = await store.load_session(member.id)
    assert session is not None
    assert not session.expired
    assert session.password_ciphertext == b"pw"


async def test_personal_tokens(engine: AsyncEngine) -> None:
    store = Store(engine)
    member = await store.upsert_member("d1", "a@example.com", None)

    grant_id, token = await store.create_personal_token(member.id, "laptop", frozenset({"read"}))

    async with engine.connect() as connection:
        stored = await connection.scalar(select(tokens.c.token_hash))
    assert stored == hash_token(token)

    owner = await store.find_token(token)
    assert owner is not None
    assert owner.member_id == member.id
    assert owner.scopes == {"read"}

    grants = await store.list_grants(member.id)
    assert [(grant.id, grant.name) for grant in grants] == [(grant_id, "laptop")]
    assert grants[0].token_hint == token[:10]
    assert grants[0].last_used_at is not None

    assert await store.find_token("dmr_unknown") is None


async def test_revoke_only_own_grant(engine: AsyncEngine) -> None:
    store = Store(engine)
    anna = await store.upsert_member("d1", "anna@example.com", None)
    bob = await store.upsert_member("d2", "bob@example.com", None)
    grant_id, token = await store.create_personal_token(anna.id, "x", frozenset({"read"}))

    assert not await store.revoke_grant(bob.id, grant_id)
    assert await store.find_token(token) is not None

    assert await store.revoke_grant(anna.id, grant_id)
    assert await store.find_token(token) is None
    assert not await store.revoke_grant(anna.id, grant_id)
    assert await store.list_grants(anna.id) == []


async def test_disabled_member_and_expired_token(engine: AsyncEngine) -> None:
    store = Store(engine)
    member = await store.upsert_member("d1", "a@example.com", None)
    _, token = await store.create_personal_token(member.id, "x", frozenset({"read"}))

    async with engine.begin() as connection:
        await connection.execute(update(tokens).values(expires_at=now() - timedelta(seconds=1)))
    assert await store.find_token(token) is None

    async with engine.begin() as connection:
        await connection.execute(update(tokens).values(expires_at=None))
        await connection.execute(update(members).values(disabled_at=now()))
    assert await store.find_token(token) is None
    assert await store.member_disabled(member.id)


async def test_personal_token_with_expiry(engine: AsyncEngine) -> None:
    store = Store(engine)
    member = await store.upsert_member("e1", "a@example.com", None)
    soon = now() + timedelta(days=7)
    _, token = await store.create_personal_token(member.id, "x", frozenset({"read"}), soon)
    owner = await store.find_token(token)
    assert owner is not None
    assert owner.expires_at == soon
    [grant] = await store.list_grants(member.id)
    assert grant.expires_at == soon
