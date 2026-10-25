"""Audit log of tool calls.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("member_id", sa.UUID(), nullable=True),
        sa.Column("grant_id", sa.UUID(), nullable=True),
        sa.Column("tool", sa.String(length=64), nullable=False),
        sa.Column("page_id", sa.String(length=64), nullable=True),
        sa.Column("space_id", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"], unique=False)
    op.create_index(
        "ix_audit_log_member_id_created_at",
        "audit_log",
        ["member_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_member_id_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")
