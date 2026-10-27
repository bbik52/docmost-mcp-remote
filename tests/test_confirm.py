from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken

from docmost_mcp_remote.tools import confirm as confirm_module


def _token(grant: str) -> AccessToken:
    return AccessToken(token="t", client_id="c", scopes=["write"], claims={"grant_id": grant})


def test_state_binds_grant_tool_and_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    grant = "g1"
    monkeypatch.setattr(confirm_module, "get_access_token", lambda: _token(grant))
    call = {"name": "trash_page", "arguments": {"page": "p1"}}
    first = confirm_module._state("Trash it?", call)
    assert first == confirm_module._state("Trash it?", dict(call))
    assert first != confirm_module._state("Trash it?", {**call, "arguments": {"page": "p2"}})
    assert first != confirm_module._state("Trash it?", {**call, "name": "restore_page"})
    assert first != confirm_module._state("Trash that?", call)
    grant = "g2"
    assert first != confirm_module._state("Trash it?", call)


async def test_a_failed_question_stops_the_change(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(**_: Any) -> Any:
        raise RuntimeError("dialog closed")

    session = SimpleNamespace(
        client_capabilities=SimpleNamespace(elicitation=object()), elicit=broken
    )
    context = SimpleNamespace(
        session=session,
        request_context=SimpleNamespace(protocol_version="2025-06-18"),
        request_id="1",
    )
    monkeypatch.setattr(confirm_module, "get_context", lambda: context)
    with pytest.raises(ToolError, match="could not ask the person"):
        await confirm_module.confirm("Trash it?")


async def test_clients_that_cannot_ask_are_not_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    session = SimpleNamespace(client_capabilities=SimpleNamespace(elicitation=None))
    monkeypatch.setattr(confirm_module, "get_context", lambda: SimpleNamespace(session=session))
    assert await confirm_module.confirm("Trash it?") == "unsupported"
