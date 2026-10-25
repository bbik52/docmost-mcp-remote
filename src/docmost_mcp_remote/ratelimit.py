"""In-memory sliding-window rate limits.

State lives in the process, which fits the single-instance deployment the
project supports. Running several replicas multiplies the limits.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 100_000,
    ) -> None:
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}

    def _recent(self, key: str, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        return hits

    def hit(self, key: str) -> bool:
        """Record an attempt; False when the key is over its limit (the attempt is not counted)."""
        now = self._clock()
        if len(self._hits) >= self._max_keys:
            self._prune(now)
        hits = self._recent(key, now)
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def _prune(self, now: float) -> None:
        for key in list(self._hits):
            if not self._recent(key, now):
                del self._hits[key]
        if len(self._hits) >= self._max_keys:
            # Still full: drop the oldest entries rather than grow without bound.
            for key in list(self._hits)[: len(self._hits) // 2]:
                del self._hits[key]
