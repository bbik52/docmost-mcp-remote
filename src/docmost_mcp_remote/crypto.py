"""Encryption of stored Docmost credentials and hashing of issued tokens.

Stored secrets are encrypted with AES-256-GCM. The key is derived from
``SECRET_KEY`` with HKDF, so the database alone does not reveal any Docmost
session. Each ciphertext records the id of the key that made it, which lets
``SECRET_KEY_PREVIOUS`` decrypt old rows during a rotation.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_FORMAT_VERSION = b"\x01"
_KEY_ID_BYTES = 8
_NONCE_BYTES = 12
TOKEN_PREFIX = "dmr_"  # noqa: S105 - a public prefix, not a secret


class DecryptionError(Exception):
    """The ciphertext was made with an unknown key or was tampered with."""


def derive_key(secret: str, purpose: str) -> bytes:
    """Derive a 32-byte key for one purpose from the configured secret."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"docmost-mcp-remote",
        info=purpose.encode(),
    )
    return hkdf.derive(secret.encode())


class _Key:
    def __init__(self, secret: str) -> None:
        self.material = derive_key(secret, "stored-credentials-v1")
        self.key_id = hashlib.sha256(self.material).digest()[:_KEY_ID_BYTES]
        self.aead = AESGCM(self.material)


class Cipher:
    """Encrypts with the current key, decrypts with the current or previous key."""

    def __init__(self, secret: str, previous: str | None = None) -> None:
        self._current = _Key(secret)
        self._keys = {self._current.key_id: self._current}
        if previous:
            old = _Key(previous)
            self._keys.setdefault(old.key_id, old)

    def encrypt(self, plaintext: str, *, context: str) -> bytes:
        """Encrypt ``plaintext``; ``context`` (for example a member id) must match on decrypt."""
        return self.encrypt_bytes(plaintext.encode(), context=context)

    def encrypt_bytes(self, data: bytes, *, context: str) -> bytes:
        nonce = secrets.token_bytes(_NONCE_BYTES)
        sealed = self._current.aead.encrypt(nonce, data, context.encode())
        return _FORMAT_VERSION + self._current.key_id + nonce + sealed

    def decrypt(self, blob: bytes, *, context: str) -> str:
        return self.decrypt_bytes(blob, context=context).decode()

    def decrypt_bytes(self, blob: bytes, *, context: str) -> bytes:
        if len(blob) < 1 + _KEY_ID_BYTES + _NONCE_BYTES or blob[:1] != _FORMAT_VERSION:
            raise DecryptionError("unknown ciphertext format")
        key_id = blob[1 : 1 + _KEY_ID_BYTES]
        key = self._keys.get(key_id)
        if key is None:
            raise DecryptionError("ciphertext was made with an unknown key")
        nonce = blob[1 + _KEY_ID_BYTES : 1 + _KEY_ID_BYTES + _NONCE_BYTES]
        try:
            plaintext = key.aead.decrypt(
                nonce, blob[1 + _KEY_ID_BYTES + _NONCE_BYTES :], context.encode()
            )
        except InvalidTag:
            raise DecryptionError("ciphertext failed authentication") from None
        return plaintext

    def needs_rotation(self, blob: bytes) -> bool:
        """True when ``blob`` was made with the previous key and should be re-encrypted."""
        return blob[1 : 1 + _KEY_ID_BYTES] != self._current.key_id


def new_token() -> str:
    """A new bearer token: prefix plus 256 bits of randomness."""
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    """Tokens are random and long, so a plain SHA-256 is enough to store them."""
    return hashlib.sha256(token.encode()).digest()


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())
