"""Member sign-in and access to each member's Docmost session."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from docmost_mcp_remote.config import Settings
from docmost_mcp_remote.crypto import Cipher, DecryptionError
from docmost_mcp_remote.db.store import Member, Store
from docmost_mcp_remote.docmost import (
    DocmostAuthError,
    DocmostBackend,
    DocmostClient,
    DocmostError,
    DocmostUnavailableError,
    UnsupportedDocmostVersionError,
)

logger = logging.getLogger(__name__)

GENERIC_SIGN_IN_ERROR = "Sign-in failed. Check your email and password."


class SignInError(Exception):
    """Sign-in was refused; the message is safe to show on the login page."""


class SessionExpiredError(Exception):
    """The member must sign in again; the message tells them where."""


class MemberService:
    def __init__(
        self, settings: Settings, store: Store, docmost: DocmostClient, cipher: Cipher
    ) -> None:
        self._settings = settings
        self._store = store
        self._docmost = docmost
        self._cipher = cipher

    @property
    def login_url(self) -> str:
        return f"{self._settings.public_base}/login"

    async def sign_in(self, email: str, password: str) -> Member:
        email = email.strip()
        if not email or not password:
            raise SignInError(GENERIC_SIGN_IN_ERROR)
        try:
            token = await self._docmost.login(email, password)
            session = self._docmost.session(token)
            check = await session.version()
            user = await session.current_user()
        except DocmostAuthError:
            raise SignInError(GENERIC_SIGN_IN_ERROR) from None
        except UnsupportedDocmostVersionError as exc:
            logger.error("Sign-in refused: %s", exc)
            raise SignInError(
                "This Docmost version is not supported by the server. Contact the administrator."
            ) from None
        except DocmostUnavailableError as exc:
            logger.warning("Sign-in failed, Docmost unavailable: %s", exc)
            raise SignInError("Docmost is not available right now. Try again later.") from None
        except DocmostError as exc:
            logger.warning("Sign-in failed: %s", exc)
            raise SignInError(GENERIC_SIGN_IN_ERROR) from None
        # Checked after Docmost answered, against the email Docmost knows, with the
        # message of a wrong password: neither the answer nor its timing tells
        # whether an email is on the allowlist.
        if not self._settings.email_allowed(user.email):
            raise SignInError(GENERIC_SIGN_IN_ERROR)
        if check.version is None:
            logger.warning(
                "Docmost did not report its version (its version check against GitHub "
                "failed); assuming a supported version"
            )
        elif not check.tested:
            logger.warning(
                "Docmost %s is newer than the tested versions; please report problems",
                check.version,
            )

        member = await self._store.upsert_member(user.id, user.email, user.name)
        if await self._store.member_disabled(member.id):
            raise SignInError("This account is disabled on this server.")
        context = str(member.id)
        stored_password = (
            self._cipher.encrypt(password, context=context)
            if self._settings.relogin_mode == "stored_password"
            else None
        )
        await self._store.save_session(
            member.id, self._cipher.encrypt(token, context=context), stored_password
        )
        logger.info("Member %s signed in", member.id)
        return member

    async def docmost_user_id(self, member_id: uuid.UUID) -> str | None:
        """The member's own Docmost user id."""
        member = await self._store.get_member(member_id)
        return member.docmost_user_id if member is not None else None

    async def _token(self, member_id: uuid.UUID) -> str:
        stored = await self._store.load_session(member_id)
        if stored is None or stored.expired:
            raise self._expired()
        context = str(member_id)
        try:
            token = self._cipher.decrypt(stored.token_ciphertext, context=context)
        except DecryptionError:
            logger.error("Cannot decrypt the Docmost session of member %s", member_id)
            raise self._expired() from None
        if self._cipher.needs_rotation(stored.token_ciphertext):
            password = None
            if stored.password_ciphertext is not None:
                password = self._decrypt_password(member_id, stored.password_ciphertext)
            await self._save(member_id, token, password)
        return token

    def _decrypt_password(self, member_id: uuid.UUID, blob: bytes) -> str | None:
        try:
            return self._cipher.decrypt(blob, context=str(member_id))
        except DecryptionError:
            return None

    async def _save(self, member_id: uuid.UUID, token: str, password: str | None) -> None:
        context = str(member_id)
        await self._store.save_session(
            member_id,
            self._cipher.encrypt(token, context=context),
            self._cipher.encrypt(password, context=context) if password else None,
        )

    def _expired(self) -> SessionExpiredError:
        return SessionExpiredError(
            f"Your Docmost session has expired. Sign in again at {self.login_url}"
        )

    async def _relogin(self, member_id: uuid.UUID) -> str | None:
        """Sign in again with the stored password; None when that is not possible."""
        if self._settings.relogin_mode != "stored_password":
            return None
        stored = await self._store.load_session(member_id)
        member = await self._store.get_member(member_id)
        if stored is None or stored.password_ciphertext is None or member is None:
            return None
        password = self._decrypt_password(member_id, stored.password_ciphertext)
        if password is None:
            return None
        try:
            token = await self._docmost.login(member.email, password)
        except DocmostAuthError:
            logger.info("Stored password of member %s no longer works", member_id)
            return None
        await self._save(member_id, token, password)
        logger.info("Member %s signed in again with the stored password", member_id)
        return token

    async def run[T](
        self, member_id: uuid.UUID, action: Callable[[DocmostBackend], Awaitable[T]]
    ) -> T:
        """Run ``action`` with the member's Docmost session, handling session expiry."""
        if await self._store.member_disabled(member_id):
            raise SessionExpiredError("This account is disabled on this server.")
        member = await self._store.get_member(member_id)
        if member is None or not self._settings.email_allowed(member.email):
            raise SessionExpiredError("This account may no longer use this server.")
        token = await self._token(member_id)
        try:
            return await action(self._docmost.session(token))
        except DocmostAuthError:
            pass
        token_or_none = await self._relogin(member_id)
        if token_or_none is None:
            await self._store.expire_session(member_id)
            raise self._expired() from None
        return await action(self._docmost.session(token_or_none))
