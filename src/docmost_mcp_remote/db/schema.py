"""Table definitions (SQLAlchemy Core). Migrations in ``migrations/`` create them."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def _now() -> Column[datetime]:
    return Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now())


#: A person who signed in with their Docmost account.
members = Table(
    "members",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("docmost_user_id", String(64), nullable=False, unique=True),
    Column("email", String(320), nullable=False),
    Column("name", Text),
    _now(),
    Column("last_login_at", DateTime(timezone=True)),
    Column("disabled_at", DateTime(timezone=True)),
    #: Web sessions signed in before this time are no longer accepted.
    Column("web_sessions_after", DateTime(timezone=True)),
)

#: The member's Docmost session, encrypted. One row per member.
docmost_sessions = Table(
    "docmost_sessions",
    metadata,
    Column(
        "member_id",
        UUID(as_uuid=True),
        ForeignKey("members.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("token_ciphertext", LargeBinary, nullable=False),
    #: Only set when RELOGIN_MODE=stored_password.
    Column("password_ciphertext", LargeBinary),
    Column("expired_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

#: Permission a member gave one client (a personal token or an OAuth client).
grants = Table(
    "grants",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "member_id",
        UUID(as_uuid=True),
        ForeignKey("members.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("kind", String(16), nullable=False),
    Column("name", String(200), nullable=False),
    #: Space-separated scopes: read, write, delete.
    Column("scopes", String(100), nullable=False),
    Column("client_id", String(200)),
    _now(),
    Column("last_used_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
)

#: Bearer tokens, stored as SHA-256 hashes.
tokens = Table(
    "tokens",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "grant_id",
        UUID(as_uuid=True),
        ForeignKey("grants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("kind", String(16), nullable=False),
    Column("token_hash", LargeBinary, nullable=False, unique=True),
    #: First characters of the token, shown so members can tell tokens apart.
    Column("hint", String(16), nullable=False),
    _now(),
    Column("expires_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
    #: RFC 8707 resource the token is bound to (OAuth tokens only).
    Column("resource", String(500)),
    #: Scopes of this token when narrower than the grant (OAuth refresh with ``scope``).
    Column("scopes", String(100)),
    #: Set when a refresh token was exchanged; presenting it again revokes the grant.
    Column("replaced_at", DateTime(timezone=True)),
)

Index("ix_members_email", members.c.email)

#: OAuth clients registered through dynamic client registration.
oauth_clients = Table(
    "oauth_clients",
    metadata,
    Column("client_id", String(64), primary_key=True),
    #: The full client metadata as registered (RFC 7591), JSON.
    Column("info", Text, nullable=False),
    _now(),
)

#: Authorization requests waiting for the member's consent.
oauth_requests = Table(
    "oauth_requests",
    metadata,
    Column("id_hash", LargeBinary, primary_key=True),
    Column(
        "client_id",
        String(64),
        ForeignKey("oauth_clients.client_id", ondelete="CASCADE"),
        nullable=False,
    ),
    #: AuthorizationParams as JSON.
    Column("params", Text, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)

#: Issued authorization codes, single use.
oauth_codes = Table(
    "oauth_codes",
    metadata,
    Column("code_hash", LargeBinary, primary_key=True),
    Column(
        "grant_id",
        UUID(as_uuid=True),
        ForeignKey("grants.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("client_id", String(64), nullable=False),
    Column("code_challenge", String(128), nullable=False),
    Column("redirect_uri", Text, nullable=False),
    Column("redirect_uri_provided_explicitly", Boolean, nullable=False),
    Column("scopes", String(100), nullable=False),
    Column("resource", String(500)),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True)),
)

#: Page bodies saved before every body write, encrypted, kept for SNAPSHOT_RETENTION_DAYS.
snapshots = Table(
    "snapshots",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "member_id",
        UUID(as_uuid=True),
        ForeignKey("members.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("page_id", String(64), nullable=False),
    Column("space_id", String(64), nullable=False),
    #: The tool call that caused the write, for example ``update_page:replace``.
    Column("reason", String(64), nullable=False),
    #: Title and body, encrypted together with the snapshot id as context.
    Column("ciphertext", LargeBinary, nullable=False),
    Column("content_chars", Integer, nullable=False),
    _now(),
)

Index("ix_snapshots_page_id_created_at", snapshots.c.page_id, snapshots.c.created_at)
Index("ix_snapshots_created_at", snapshots.c.created_at)

#: One row per tool call: who, which tool, which page, the outcome. Never content or arguments.
audit_log = Table(
    "audit_log",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    _now(),
    #: No foreign keys: entries outlive members and grants.
    Column("member_id", UUID(as_uuid=True)),
    Column("grant_id", UUID(as_uuid=True)),
    Column("tool", String(64), nullable=False),
    Column("page_id", String(64)),
    Column("space_id", String(64)),
    #: ok, error or rate_limited.
    Column("outcome", String(16), nullable=False),
    Column("duration_ms", Integer, nullable=False),
)

Index("ix_audit_log_created_at", audit_log.c.created_at)
Index("ix_audit_log_member_id_created_at", audit_log.c.member_id, audit_log.c.created_at)

#: Upload links: a page the member lets someone add files to, until expires_at.
upload_links = Table(
    "upload_links",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "member_id",
        UUID(as_uuid=True),
        ForeignKey("members.id", ondelete="CASCADE"),
        nullable=False,
    ),
    #: The grant that made the link; revoking it ends the link. Empty in links
    #: made before 1.2.1, which no longer work.
    Column(
        "grant_id",
        UUID(as_uuid=True),
        ForeignKey("grants.id", ondelete="CASCADE"),
    ),
    #: SHA-256 of the token in the link.
    Column("token_hash", LargeBinary, nullable=False, unique=True),
    Column("page_id", String(64), nullable=False),
    #: Page title, link and where files go, encrypted with the link id as context.
    Column("details", LargeBinary, nullable=False),
    #: open, adding (files are going to Docmost), done.
    Column("state", String(16), nullable=False),
    #: Why the last attempt to add the files failed, or the outcome once done, JSON.
    Column("outcome", Text),
    _now(),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)

Index("ix_upload_links_expires_at", upload_links.c.expires_at)

#: Files sent to an upload link. Content is kept, encrypted, only until it is in Docmost.
upload_files = Table(
    "upload_files",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "link_id",
        UUID(as_uuid=True),
        ForeignKey("upload_links.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("file_name", String(255), nullable=False),
    Column("mime_type", String(255), nullable=False),
    Column("size", Integer, nullable=False),
    #: Order of arrival; the page gets the files in this order unless told otherwise.
    Column("position", Integer, nullable=False),
    Column("ciphertext", LargeBinary),
    #: The Docmost attachment once uploaded there.
    Column("attachment_id", String(64)),
    _now(),
)
