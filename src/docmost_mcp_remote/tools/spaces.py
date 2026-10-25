"""Admin restriction of the spaces members may use through this server."""

from __future__ import annotations

from fastmcp.exceptions import ToolError

from docmost_mcp_remote.docmost import DocmostBackend
from docmost_mcp_remote.docmost.models import Space

_MAX_SPACE_PAGES = 20


class SpacePolicy:
    """``ALLOWED_SPACES`` holds slugs or ids; checks resolve them against the member's spaces."""

    def __init__(self, allowed: frozenset[str]) -> None:
        self._allowed = allowed

    @property
    def restricted(self) -> bool:
        return bool(self._allowed)

    def allows_space(self, space: Space) -> bool:
        return not self._allowed or space.id in self._allowed or space.slug in self._allowed

    async def allowed_ids(self, backend: DocmostBackend) -> frozenset[str] | None:
        """Ids of allowed spaces the member can see; None when there is no restriction."""
        if not self._allowed:
            return None
        ids: set[str] = set()
        cursor: str | None = None
        for _ in range(_MAX_SPACE_PAGES):
            page = await backend.list_spaces(cursor=cursor, limit=100)
            ids.update(space.id for space in page.items if self.allows_space(space))
            if not page.has_next_page or not page.next_cursor:
                break
            cursor = page.next_cursor
        return frozenset(ids)

    async def check(self, backend: DocmostBackend, space_id: str) -> None:
        self.ensure(await self.allowed_ids(backend), space_id)

    @staticmethod
    def ensure(allowed: frozenset[str] | None, space_id: str) -> None:
        if allowed is not None and space_id not in allowed:
            # Same wording as Docmost's own answer for spaces the member cannot see.
            raise ToolError("Docmost: Space not found")
