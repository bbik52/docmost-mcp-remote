"""Asking the person, not the model, before a risky change.

The question goes to the person through the client (MCP elicitation), so a
model misled by text in a page cannot answer it. Clients that cannot ask
are not blocked: the change then goes ahead as before, and the scopes the
person granted remain the limit.

Two protocol eras ask differently. Before MCP 2026-07-28 the server sends
the question while the tool call waits. From 2026-07-28 the tool answers
with an ``InputRequiredResult``; the client asks the person and calls the
tool again with the answer, which is matched to the same change through
the request state.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

import mcp_types as mt
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_context
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

logger = logging.getLogger(__name__)

_KEY = "confirm"
_SCHEMA = {
    "type": "object",
    "properties": {"confirm": {"type": "boolean", "title": "Yes, do it"}},
    "required": ["confirm"],
}
DECLINED = "Nothing was done: the person declined in their client."

Answer = Literal["yes", "unsupported"]


def named(text: str | None, limit: int = 80) -> str:
    """A name from Docmost, quoted and shortened, for a question."""
    text = " ".join((text or "(untitled)").split())
    return f'"{text[:limit]}…"' if len(text) > limit else f'"{text}"'


def _accepted(result: object) -> bool:
    content = getattr(result, "content", None) or {}
    return getattr(result, "action", None) == "accept" and content.get("confirm") is True


async def confirm(
    question: str | Callable[[], Awaitable[str]],
) -> Answer | mt.InputRequiredResult:
    """Ask the person to confirm ``question``, or the text it makes when it is a function.

    A function is called only when the client can ask. Returns "yes",
    "unsupported" when the client cannot ask, or an ``InputRequiredResult``
    that the tool must return as it is. Raises a ``ToolError`` when the person
    declines or dismisses the question.
    """
    ctx = get_context()
    session = ctx.session
    capabilities = session.client_capabilities if session is not None else None
    if capabilities is None or capabilities.elicitation is None:
        return "unsupported"
    if not isinstance(question, str):
        question = await question()
    request = ctx.request_context
    if request is not None and request.protocol_version in MODERN_PROTOCOL_VERSIONS:
        state = f"{_KEY}:{hashlib.sha256(question.encode()).hexdigest()}"
        answers = ctx.input_responses
        if answers is not None and _KEY in answers and ctx.request_state == state:
            if _accepted(answers[_KEY]):
                return "yes"
            raise ToolError(DECLINED)
        ask = mt.ElicitRequest(
            params=mt.ElicitRequestFormParams(message=question, requested_schema=_SCHEMA)
        )
        return mt.InputRequiredResult(input_requests={_KEY: ask}, request_state=state)
    try:
        result = await session.elicit(
            message=question, requested_schema=_SCHEMA, related_request_id=ctx.request_id
        )
    except Exception as exc:  # A client that declared elicitation but cannot do it.
        logger.warning("Asking for confirmation failed: %s", exc)
        return "unsupported"
    if _accepted(result):
        return "yes"
    raise ToolError(DECLINED)
