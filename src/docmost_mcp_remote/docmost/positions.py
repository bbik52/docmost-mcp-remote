"""Sibling order keys for ``pages/move``.

Docmost orders pages by a string key compared byte by byte. A key is an
integer part (a head letter that encodes its length, then base-62 digits)
followed by an optional fraction that never ends in ``0``; Docmost accepts
keys of 5 to 12 characters. This module only builds keys between two
existing ones; it never parses page content.
"""

from __future__ import annotations

DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
MIN_LENGTH = 5
MAX_LENGTH = 12
_SMALLEST_INTEGER = "A" + "0" * 26


class PositionError(ValueError):
    """No key fits, or an existing key is malformed."""


def _integer_length(head: str) -> int:
    if "a" <= head <= "z":
        return ord(head) - ord("a") + 2
    if "A" <= head <= "Z":
        return ord("Z") - ord(head) + 2
    raise PositionError(f"invalid position head {head!r}")


def _split(key: str) -> tuple[str, str]:
    if not key:
        raise PositionError("empty position")
    length = _integer_length(key[0])
    integer, fraction = key[:length], key[length:]
    if len(integer) < length or any(char not in DIGITS for char in key[1:]):
        raise PositionError(f"invalid position {key!r}")
    if fraction.endswith("0"):
        raise PositionError(f"invalid position {key!r}")
    return integer, fraction


def _increment(integer: str) -> str | None:
    head, digits = integer[0], list(integer[1:])
    for index in range(len(digits) - 1, -1, -1):
        value = DIGITS.index(digits[index]) + 1
        if value < len(DIGITS):
            digits[index] = DIGITS[value]
            return head + "".join(digits)
        digits[index] = "0"
    if head == "Z":
        return "a0"
    if head == "z":
        return None
    new_head = chr(ord(head) + 1)
    if new_head > "a":
        digits.append("0")
    else:
        digits.pop()
    return new_head + "".join(digits)


def _decrement(integer: str) -> str | None:
    head, digits = integer[0], list(integer[1:])
    for index in range(len(digits) - 1, -1, -1):
        value = DIGITS.index(digits[index]) - 1
        if value >= 0:
            digits[index] = DIGITS[value]
            return head + "".join(digits)
        digits[index] = DIGITS[-1]
    if head == "a":
        return "Z" + DIGITS[-1]
    if head == "A":
        return None
    new_head = chr(ord(head) - 1)
    if new_head < "Z":
        digits.append(DIGITS[-1])
    else:
        digits.pop()
    return new_head + "".join(digits)


def _midpoint(low: str, high: str | None) -> str:
    """A fraction strictly between ``low`` and ``high`` (None: the end)."""
    if high is not None:
        common = 0
        while common < len(high) and (low[common] if common < len(low) else "0") == high[common]:
            common += 1
        if common:
            return high[:common] + _midpoint(low[common:], high[common:])
    low_digit = DIGITS.index(low[0]) if low else 0
    high_digit = DIGITS.index(high[0]) if high else len(DIGITS)
    if high_digit - low_digit > 1:
        return DIGITS[(low_digit + high_digit + 1) // 2]
    if high is not None and len(high) > 1:
        return high[0]
    return DIGITS[low_digit] + _midpoint(low[1:], None)


def _between(low: str | None, high: str | None) -> str:
    if low is None:
        if high is None:
            return "a0"
        integer, fraction = _split(high)
        # A smaller integer keeps keys short when pages are added at the start again and again.
        smaller = _decrement(integer)
        if smaller is not None:
            return smaller
        if integer == _SMALLEST_INTEGER and fraction:
            return integer + _midpoint("", fraction)
        raise PositionError("no position before the first page")
    low_integer, low_fraction = _split(low)
    if high is None:
        larger = _increment(low_integer)
        return larger if larger is not None else low_integer + _midpoint(low_fraction, None)
    high_integer, high_fraction = _split(high)
    if low_integer == high_integer:
        return low_integer + _midpoint(low_fraction, high_fraction)
    larger = _increment(low_integer)
    if larger is not None and larger < high:
        return larger
    return low_integer + _midpoint(low_fraction, None)


def position_between(low: str | None, high: str | None) -> str:
    """A key that sorts after ``low`` and before ``high``, 5 to 12 characters long."""
    if low is not None and high is not None and low >= high:
        raise PositionError("positions are out of order")
    key = _between(low, high)
    while len(key) < MIN_LENGTH:
        if high is not None and high.startswith(key):
            key += _midpoint("", high[len(key) :])
        else:
            # Any longer key with this prefix still sorts before ``high``.
            key += DIGITS[len(DIGITS) // 2]
    if len(key) > MAX_LENGTH:
        raise PositionError("no room for a position between these pages")
    return key
