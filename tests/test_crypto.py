from __future__ import annotations

import pytest

from docmost_mcp_remote.crypto import (
    TOKEN_PREFIX,
    Cipher,
    DecryptionError,
    hash_token,
    new_token,
)

KEY = "k" * 40
OTHER = "o" * 40


def test_round_trip() -> None:
    cipher = Cipher(KEY)
    blob = cipher.encrypt("docmost-token", context="member-1")
    assert b"docmost-token" not in blob
    assert cipher.decrypt(blob, context="member-1") == "docmost-token"


def test_context_is_bound() -> None:
    cipher = Cipher(KEY)
    blob = cipher.encrypt("docmost-token", context="member-1")
    with pytest.raises(DecryptionError):
        cipher.decrypt(blob, context="member-2")


def test_tampering_is_detected() -> None:
    cipher = Cipher(KEY)
    blob = bytearray(cipher.encrypt("docmost-token", context="m"))
    blob[-1] ^= 1
    with pytest.raises(DecryptionError):
        cipher.decrypt(bytes(blob), context="m")


def test_unknown_key() -> None:
    blob = Cipher(OTHER).encrypt("x", context="m")
    with pytest.raises(DecryptionError, match="unknown key"):
        Cipher(KEY).decrypt(blob, context="m")


def test_rotation_with_previous_key() -> None:
    old_blob = Cipher(OTHER).encrypt("x", context="m")
    rotated = Cipher(KEY, previous=OTHER)

    assert rotated.decrypt(old_blob, context="m") == "x"
    assert rotated.needs_rotation(old_blob)
    assert not rotated.needs_rotation(rotated.encrypt("x", context="m"))


def test_garbage() -> None:
    with pytest.raises(DecryptionError):
        Cipher(KEY).decrypt(b"short", context="m")


def test_tokens() -> None:
    first, second = new_token(), new_token()
    assert first.startswith(TOKEN_PREFIX)
    assert first != second
    assert len(first) > 40
    assert hash_token(first) == hash_token(first)
    assert hash_token(first) != hash_token(second)
