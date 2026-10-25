"""Member sign-in against a real Docmost and Postgres."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from docmost_mcp_remote.crypto import Cipher
from docmost_mcp_remote.db.store import Store
from docmost_mcp_remote.docmost import CeDocmostClient, DocmostBackend
from docmost_mcp_remote.members import MemberService, SignInError
from tests.conftest import SECRET, make_settings
from tests.integration.conftest import DOCMOST_URL, MEMBER

pytestmark = pytest.mark.integration


async def test_sign_in_and_run(
    engine: AsyncEngine, client: CeDocmostClient, tokens: dict[str, str]
) -> None:
    settings = make_settings(docmost_url=DOCMOST_URL, docmost_allow_insecure_http=True)
    members = MemberService(settings, Store(engine), client, Cipher(SECRET))

    member = await members.sign_in(*MEMBER)

    async def email(backend: DocmostBackend) -> str:
        return (await backend.current_user()).email

    assert await members.run(member.id, email) == MEMBER[0]

    with pytest.raises(SignInError):
        await members.sign_in(MEMBER[0], "wrong-password")
