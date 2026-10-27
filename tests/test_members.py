from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.crypto import Cipher
from docmost_mcp_remote.db.schema import docmost_sessions
from docmost_mcp_remote.db.store import Store
from docmost_mcp_remote.docmost import DocmostBackend
from docmost_mcp_remote.members import (
    GENERIC_SIGN_IN_ERROR,
    MemberService,
    SessionExpiredError,
    SignInError,
)
from tests.conftest import SECRET, make_settings
from tests.fakes import Recorder, docmost_routes, error, ok


def service(
    engine: AsyncEngine, mock: Recorder, cipher: Cipher | None = None, **settings: object
) -> MemberService:
    return MemberService(
        make_settings(**settings), Store(engine), mock.client(), cipher or Cipher(SECRET)
    )


async def whoami(backend: DocmostBackend) -> str:
    return (await backend.current_user()).email


async def test_sign_in_stores_only_encrypted_token(engine: AsyncEngine) -> None:
    members = service(engine, Recorder(docmost_routes()))

    member = await members.sign_in("anna@example.com", "pw")

    async with engine.connect() as connection:
        row = (await connection.execute(select(docmost_sessions))).one()
    assert b"docmost-token" not in row.token_ciphertext
    assert row.password_ciphertext is None
    assert await members.run(member.id, whoami) == "anna@example.com"


async def test_wrong_password_is_generic(engine: AsyncEngine) -> None:
    members = service(engine, Recorder(docmost_routes()))
    with pytest.raises(SignInError, match=GENERIC_SIGN_IN_ERROR):
        await members.sign_in("anna@example.com", "wrong")


async def test_allowlist_refuses_without_calling_docmost(engine: AsyncEngine) -> None:
    mock = Recorder(docmost_routes())
    members = service(engine, mock, allowed_emails="bob@example.com")

    with pytest.raises(SignInError, match=GENERIC_SIGN_IN_ERROR):
        await members.sign_in("anna@example.com", "pw")
    assert mock.requests == []


async def test_old_docmost_is_refused(engine: AsyncEngine) -> None:
    members = service(engine, Recorder(docmost_routes(version="0.60.0")))
    with pytest.raises(SignInError, match="not supported"):
        await members.sign_in("anna@example.com", "pw")


async def test_docmost_down(engine: AsyncEngine) -> None:
    routes = docmost_routes()
    routes["/api/auth/login"] = error(503, "down")
    members = service(engine, Recorder(routes))
    with pytest.raises(SignInError, match="not available"):
        await members.sign_in("anna@example.com", "pw")


async def test_expired_session_asks_to_sign_in_again(engine: AsyncEngine) -> None:
    routes = docmost_routes()
    mock = Recorder(routes)
    members = service(engine, mock)
    member = await members.sign_in("anna@example.com", "pw")

    routes["/api/users/me"] = error(401, "Unauthorized")
    with pytest.raises(SessionExpiredError, match=r"https://mcp\.example\.com/login"):
        await members.run(member.id, whoami)

    # The session stays expired until the member signs in again.
    routes.update(docmost_routes())
    with pytest.raises(SessionExpiredError):
        await members.run(member.id, whoami)
    await members.sign_in("anna@example.com", "pw")
    assert await members.run(member.id, whoami) == "anna@example.com"


async def test_stored_password_relogin(engine: AsyncEngine) -> None:
    routes = docmost_routes(token="first")
    mock = Recorder(routes)
    members = service(engine, mock, relogin_mode="stored_password")
    member = await members.sign_in("anna@example.com", "pw")

    async with engine.connect() as connection:
        row = (await connection.execute(select(docmost_sessions))).one()
    assert row.password_ciphertext is not None
    assert b"pw" not in row.password_ciphertext

    # Docmost now only accepts a new token, which the next sign-in returns.
    routes.update(docmost_routes(token="second"))
    assert await members.run(member.id, whoami) == "anna@example.com"
    logins = [r for r in mock.requests if r.url.path == "/api/auth/login"]
    assert len(logins) == 2

    # The new token is stored: no further sign-in is needed.
    assert await members.run(member.id, whoami) == "anna@example.com"
    assert len([r for r in mock.requests if r.url.path == "/api/auth/login"]) == 2


async def test_stored_password_no_longer_valid(engine: AsyncEngine) -> None:
    routes = docmost_routes(token="first")
    members = service(engine, Recorder(routes), relogin_mode="stored_password")
    member = await members.sign_in("anna@example.com", "pw")

    routes.update(docmost_routes(token="second", password="changed"))
    with pytest.raises(SessionExpiredError):
        await members.run(member.id, whoami)


async def test_key_rotation_reencrypts(engine: AsyncEngine) -> None:
    old_key = "old-secret-key-0123456789abcdef-0123"
    mock = Recorder(docmost_routes())
    member = await service(engine, mock, Cipher(old_key)).sign_in("anna@example.com", "pw")

    rotated = Cipher(SECRET, previous=old_key)
    assert await service(engine, mock, rotated).run(member.id, whoami) == "anna@example.com"

    async with engine.connect() as connection:
        blob = (await connection.execute(select(docmost_sessions))).one().token_ciphertext
    assert not rotated.needs_rotation(blob)
    # Readable with the new key alone.
    assert await service(engine, mock, Cipher(SECRET)).run(member.id, whoami)


async def test_unknown_member_must_sign_in(engine: AsyncEngine) -> None:
    import uuid

    members = service(engine, Recorder({"/api/users/me": ok({})}))
    with pytest.raises(SessionExpiredError):
        await members.run(uuid.uuid4(), whoami)


async def test_allowlist_applies_to_signed_in_members(engine: AsyncEngine) -> None:
    mock = Recorder(docmost_routes())
    member = await service(engine, mock).sign_in("anna@example.com", "pw")
    with pytest.raises(SessionExpiredError, match="no longer use this server"):
        await service(engine, mock, allowed_emails="bob@example.com").run(member.id, whoami)
