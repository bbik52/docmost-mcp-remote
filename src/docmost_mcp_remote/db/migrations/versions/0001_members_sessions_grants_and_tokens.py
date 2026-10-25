"""Members, Docmost sessions, grants and tokens.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("docmost_user_id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_members")),
        sa.UniqueConstraint("docmost_user_id", name=op.f("uq_members_docmost_user_id")),
    )
    op.create_index("ix_members_email", "members", ["email"], unique=False)
    op.create_table(
        "docmost_sessions",
        sa.Column("member_id", sa.UUID(), nullable=False),
        sa.Column("token_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("password_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["members.id"],
            name=op.f("fk_docmost_sessions_member_id_members"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("member_id", name=op.f("pk_docmost_sessions")),
    )
    op.create_table(
        "grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("member_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("scopes", sa.String(length=100), nullable=False),
        sa.Column("client_id", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["members.id"],
            name=op.f("fk_grants_member_id_members"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grants")),
    )
    op.create_index(op.f("ix_grants_member_id"), "grants", ["member_id"], unique=False)
    op.create_table(
        "tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("grant_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("hint", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["grant_id"], ["grants.id"], name=op.f("fk_tokens_grant_id_grants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_tokens_token_hash")),
    )
    op.create_index(op.f("ix_tokens_grant_id"), "tokens", ["grant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tokens_grant_id"), table_name="tokens")
    op.drop_table("tokens")
    op.drop_index(op.f("ix_grants_member_id"), table_name="grants")
    op.drop_table("grants")
    op.drop_table("docmost_sessions")
    op.drop_index("ix_members_email", table_name="members")
    op.drop_table("members")
