from __future__ import annotations

import random

import pytest

from docmost_mcp_remote.docmost.positions import PositionError, position_between

# Keys as Docmost 0.97 writes them.
EXISTING = ["a01bz", "a03j3", "a06gY", "a082B", "a17AT", "a3BKl", "aY77U"]


def _valid(key: str) -> bool:
    return 5 <= len(key) <= 12 and not key.endswith("0")


def test_empty_level() -> None:
    assert position_between(None, None) == "a0VVV"


@pytest.mark.parametrize(
    ("low", "high"),
    [
        (None, "a01bz"),
        ("aY77U", None),
        ("a01bz", "a03j3"),
        ("a06gY", "a082B"),
        ("a082B", "a17AT"),
        ("a0VVV", "a0VVW"),
        ("Zz", "a0"),
    ],
)
def test_between(low: str | None, high: str | None) -> None:
    key = position_between(low, high)
    assert _valid(key)
    assert low is None or low < key
    assert high is None or key < high


def test_many_inserts_stay_ordered() -> None:
    keys = sorted(EXISTING)
    rng = random.Random(7)  # noqa: S311
    for _ in range(2000):
        index = rng.randint(0, len(keys))
        low = keys[index - 1] if index else None
        high = keys[index] if index < len(keys) else None
        key = position_between(low, high)
        assert _valid(key)
        keys.insert(index, key)
    assert keys == sorted(keys)


def test_repeated_appends_and_prepends() -> None:
    last = first = "a0VVV"
    for _ in range(200):
        last = position_between(last, None)
        first = position_between(None, first)
        assert _valid(last)
        assert _valid(first)
    assert first < "a0VVV" < last


def test_errors() -> None:
    with pytest.raises(PositionError):
        position_between("a1VVV", "a0VVV")
    with pytest.raises(PositionError):
        position_between("!bad", None)
    with pytest.raises(PositionError):
        position_between("a0VV0", None)
