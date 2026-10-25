from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote import admin
from docmost_mcp_remote.crypto import Cipher
from docmost_mcp_remote.db.admin_store import AuditStore
from docmost_mcp_remote.db.engine import create_engine
from docmost_mcp_remote.db.snapshot_store import SnapshotStore
from docmost_mcp_remote.db.store import Store
from tests.conftest import DATABASE_TEST_URL, SECRET

OLD_KEY = "o" * 40


def _with_engine[T](action: Callable[[AsyncEngine], Awaitable[T]]) -> T:
    async def run() -> T:
        engine = create_engine(DATABASE_TEST_URL)
        try:
            return await action(engine)
        finally:
            await engine.dispose()

    return asyncio.run(run())


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, engine: AsyncEngine) -> pytest.MonkeyPatch:
    monkeypatch.setenv("PUBLIC_URL", "https://mcp.example.com")
    monkeypatch.setenv("DOCMOST_URL", "https://docs.example.com")
    monkeypatch.setenv("DATABASE_URL", DATABASE_TEST_URL)
    monkeypatch.setenv("SECRET_KEY", SECRET)
    return monkeypatch


@pytest.fixture
def anna(env: pytest.MonkeyPatch) -> dict[str, Any]:
    async def setup(engine: AsyncEngine) -> dict[str, Any]:
        store = Store(engine)
        member = await store.upsert_member("u1", "anna@example.com", "Anna")
        grant_id, token = await store.create_personal_token(
            member.id, "laptop", frozenset({"read"})
        )
        await store.save_session(
            member.id, Cipher(SECRET).encrypt("t", context=str(member.id)), None
        )
        await AuditStore(engine).record(
            member_id=member.id,
            grant_id=grant_id,
            tool="get_page",
            page_id="p1",
            space_id=None,
            outcome="ok",
            duration_ms=12,
        )
        return {"id": member.id, "grant_id": grant_id, "token": token}

    return _with_engine(setup)


def _token_works(token: str) -> bool:
    async def check(engine: AsyncEngine) -> bool:
        return await Store(engine).find_token(token) is not None

    return _with_engine(check)


def test_members_grants_and_audit(anna: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    assert admin.main(["members"]) == 0
    out = capsys.readouterr().out
    assert "anna@example.com" in out
    assert "active" in out

    assert admin.main(["grants", "ANNA@example.com"]) == 0
    assert str(anna["grant_id"]) in capsys.readouterr().out

    assert admin.main(["audit", "--email", "anna@example.com"]) == 0
    out = capsys.readouterr().out
    assert "get_page" in out
    assert "p1" in out


def test_revoke_grant(anna: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    assert admin.main(["revoke-grant", str(anna["grant_id"])]) == 0
    assert not _token_works(anna["token"])
    assert admin.main(["revoke-grant", str(anna["grant_id"])]) == 1
    assert admin.main(["revoke-grant", "nope"]) == 1


def test_revoke_member(anna: dict[str, Any]) -> None:
    assert admin.main(["revoke-member", "anna@example.com"]) == 0
    assert not _token_works(anna["token"])

    async def session(engine: AsyncEngine) -> object:
        return await Store(engine).load_session(anna["id"])

    assert _with_engine(session) is None


def test_disable_and_enable(anna: dict[str, Any]) -> None:
    assert admin.main(["disable-member", "anna@example.com"]) == 0
    assert not _token_works(anna["token"])
    assert admin.main(["enable-member", "anna@example.com"]) == 0
    assert _token_works(anna["token"])


def test_unknown_member(env: pytest.MonkeyPatch) -> None:
    assert admin.main(["grants", "nobody@example.com"]) == 1


def test_rotate_key(env: pytest.MonkeyPatch) -> None:
    old = Cipher(OLD_KEY)

    async def setup(engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID]:
        member = await Store(engine).upsert_member("u2", "bob@example.com", "Bob")
        await Store(engine).save_session(
            member.id, old.encrypt("docmost-token", context=str(member.id)), None
        )
        snapshot_id = await SnapshotStore(engine, old).save(
            member_id=member.id,
            page_id="p1",
            space_id="s1",
            title="T",
            content="body",
            reason="update_page:append",
        )
        return member.id, snapshot_id

    member_id, snapshot_id = _with_engine(setup)
    assert admin.main(["rotate-key"]) == 1  # needs SECRET_KEY_PREVIOUS
    env.setenv("SECRET_KEY_PREVIOUS", OLD_KEY)
    assert admin.main(["rotate-key"]) == 0

    new = Cipher(SECRET)

    async def check(engine: AsyncEngine) -> tuple[str, str]:
        stored = await Store(engine).load_session(member_id)
        assert stored is not None
        snapshot = await SnapshotStore(engine, new).load(member_id, snapshot_id)
        assert snapshot is not None
        return new.decrypt(stored.token_ciphertext, context=str(member_id)), snapshot.content

    assert _with_engine(check) == ("docmost-token", "body")
