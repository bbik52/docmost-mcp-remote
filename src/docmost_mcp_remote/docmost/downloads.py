"""Files read from Docmost as a stream: exports and attachments."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from docmost_mcp_remote.docmost.errors import DocmostResponseTooLargeError


@dataclass(slots=True)
class Download:
    """An open answer from Docmost; ``close`` must be awaited once it is read."""

    content_type: str
    file_name: str | None
    size: int | None
    chunks: AsyncIterator[bytes]
    close: Callable[[], Awaitable[None]]

    async def read(self, limit: int) -> bytes:
        """The whole file, refused when it is larger than ``limit`` bytes; closes it."""
        try:
            if self.size is not None and self.size > limit:
                raise DocmostResponseTooLargeError("The file is too large to return inline")
            parts: list[bytes] = []
            size = 0
            async for chunk in self.chunks:
                size += len(chunk)
                if size > limit:
                    raise DocmostResponseTooLargeError("The file is too large to return inline")
                parts.append(chunk)
            return b"".join(parts)
        finally:
            await self.close()
