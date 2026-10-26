"""Resources: wiki content that a person attaches to the conversation in their client.

Tools are chosen by the model. Resources are chosen by the person: the client
lists them, reads the one picked and puts its text into the conversation.
They run as the member, like tools, and argument completion offers the
member's own pages and spaces while the person types.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Annotated
from urllib.parse import unquote

import mcp.types as mt
from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError, ToolError
from fastmcp.server.auth import require_scopes
from pydantic import Field

from docmost_mcp_remote.auth import current_member_id
from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.docmost import DocmostBackend
from docmost_mcp_remote.docmost.models import Page
from docmost_mcp_remote.members import MemberService
from docmost_mcp_remote.ratelimit import RateLimiter
from docmost_mcp_remote.tools.common import as_member, page_link
from docmost_mcp_remote.tools.read import page_ref
from docmost_mcp_remote.tools.spaces import SpacePolicy
from docmost_mcp_remote.tools.untrusted import NOTICE, truncate, wrap

logger = logging.getLogger(__name__)

SPACES_URI = "docmost://spaces"
PAGES_PREFIX = "docmost://pages/"
PAGE_URI = PAGES_PREFIX + "{page}"
#: Candidates offered for one completion request.
COMPLETION_LIMIT = 10
_NOT_WORD = re.compile(r"[\W_]+")


def page_handle(title: str | None, slug_id: str) -> str:
    """A readable page reference: the title as a slug, then the slug id, as in page URLs."""
    words = _NOT_WORD.sub("-", (title or "").lower()).strip("-")[:40].strip("-")
    return f"{words}-{slug_id}" if words else slug_id


def page_from_uri(uri: str) -> str | None:
    """The page reference in a page resource URI, for the audit log."""
    if not uri.startswith(PAGES_PREFIX):
        return None
    return page_ref(unquote(uri.removeprefix(PAGES_PREFIX)))


def render_page(page: Page, path: list[str], url: str | None, limit: int) -> str:
    body, truncated = truncate(page.content, limit)
    lines = [NOTICE, "", f"# {page.title or '(untitled)'}", ""]
    if page.space is not None and page.space.name:
        lines.append(f"Space: {page.space.name}")
    if path:
        lines.append(f"Path: {' / '.join(path)}")
    if url:
        lines.append(f"URL: {url}")
    if page.updated_at:
        who = f" by {page.last_updated_by.name}" if page.last_updated_by else ""
        lines.append(f"Updated: {page.updated_at.date().isoformat()}{who}")
    lines.append(f"Page id: {page.id}")
    lines += ["", wrap(body, source=f"page {page.id}")]
    if truncated:
        lines += [
            "",
            f"The body is cut at {limit} characters; read the rest with get_section or "
            "get_page_outline.",
        ]
    return "\n".join(lines)


def register(mcp: FastMCP, settings: Settings, members: MemberService) -> None:
    policy = SpacePolicy(settings.allowed_spaces)
    docmost_base = str(settings.docmost_url).rstrip("/")
    # Completion runs on every keystroke, so it has its own budget and never
    # uses up the member's tool calls.
    completion_limiter = RateLimiter(settings.tool_calls_per_minute, 60)

    async def read[T](action: Callable[[DocmostBackend], Awaitable[T]]) -> T:
        try:
            return await as_member(members, action)
        except ToolError as exc:
            raise ResourceError(str(exc)) from None

    @mcp.resource(
        SPACES_URI,
        name="spaces",
        title="Docmost spaces",
        description="The Docmost spaces you can access, with your role in each.",
        mime_type="text/markdown",
        auth=require_scopes("read"),
    )
    async def spaces() -> str:
        async def action(backend: DocmostBackend) -> str:
            found = await backend.list_spaces(limit=100)
            lines = ["# Docmost spaces", ""]
            for space in found.items:
                if not policy.allows_space(space):
                    continue
                lines.append(
                    f"- {space.name or '(unnamed)'}: slug {space.slug}, id {space.id}, "
                    f"your role {space.member_role or 'unknown'}"
                )
                if space.description:
                    lines.append(f"  {space.description}")
            if found.has_next_page:
                lines += ["", "More spaces exist; list them with list_spaces."]
            return f"{NOTICE}\n\n{wrap(chr(10).join(lines), source='spaces')}"

        return await read(action)

    @mcp.resource(
        PAGE_URI,
        name="page",
        title="Docmost page",
        description=(
            "One Docmost page as Markdown, with its title, place and link. Type part of a "
            "title to pick a page."
        ),
        mime_type="text/markdown",
        auth=require_scopes("read"),
    )
    async def page(
        page: Annotated[str, Field(description="Page slug id, id or the last part of its URL.")],
    ) -> str:
        async def action(backend: DocmostBackend) -> str:
            found = await backend.get_page(page_ref(unquote(page)))
            await policy.check(backend, found.space_id)
            trail = await backend.breadcrumbs(found.id)
            path = [item.title or "(untitled)" for item in trail[:-1]]
            return render_page(found, path, page_link(docmost_base, found), settings.max_page_chars)

        return await read(action)

    async def complete_pages(backend: DocmostBackend, typed: str) -> list[str]:
        allowed = await policy.allowed_ids(backend)
        if len(typed) < 2:
            recent = await backend.recent_pages(limit=COMPLETION_LIMIT)
            candidates = [(item.title, item.slug_id, item.space_id) for item in recent.items]
        else:
            found = await backend.suggest(typed, limit=COMPLETION_LIMIT)
            candidates = [(item.title, item.slug_id, item.space_id) for item in found.pages]
        return [
            page_handle(title, slug_id)
            for title, slug_id, space_id in candidates
            if allowed is None or space_id in allowed
        ]

    async def complete_spaces(backend: DocmostBackend, typed: str) -> list[str]:
        found = await backend.list_spaces(limit=100)
        needle = typed.lower()
        return [
            space.slug
            for space in found.items
            if space.slug
            and policy.allows_space(space)
            and (needle in space.slug.lower() or needle in (space.name or "").lower())
        ][:COMPLETION_LIMIT]

    @mcp.completion
    async def complete(
        ref: mt.PromptReference | mt.ResourceTemplateReference,
        argument: mt.CompletionArgument,
        context: mt.CompletionContext | None,
    ) -> list[str]:
        """Offer the member's pages for ``page`` arguments and spaces for ``space``."""
        if argument.name not in ("page", "space"):
            return []
        try:
            member_id = current_member_id()
        except PermissionError:
            return []
        if not completion_limiter.hit(str(member_id)):
            return []
        typed = argument.value.strip()

        async def action(backend: DocmostBackend) -> list[str]:
            if argument.name == "page":
                return await complete_pages(backend, typed)
            return await complete_spaces(backend, typed)

        try:
            return await members.run(member_id, action)
        except Exception as exc:
            # A failed suggestion only means no suggestions.
            logger.debug("Completion failed: %s", exc)
            return []
