from __future__ import annotations

from docmost_mcp_remote.ratelimit import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_limit_and_window() -> None:
    clock = Clock()
    limiter = RateLimiter(2, 60, clock=clock)

    assert limiter.hit("a")
    assert limiter.hit("a")
    assert not limiter.hit("a")
    assert limiter.hit("b")

    clock.now = 61
    assert limiter.hit("a")


def test_reset() -> None:
    limiter = RateLimiter(1, 60, clock=Clock())
    assert limiter.hit("a")
    assert not limiter.hit("a")
    limiter.reset("a")
    assert limiter.hit("a")


def test_memory_is_bounded() -> None:
    clock = Clock()
    limiter = RateLimiter(1, 60, clock=clock, max_keys=10)
    for index in range(100):
        limiter.hit(str(index))
    assert len(limiter._hits) <= 10
