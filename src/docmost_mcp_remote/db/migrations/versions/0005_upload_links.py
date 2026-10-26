"""Upload links and the files sent to them.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "upload_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("member_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("page_id", sa.String(length=64), nullable=False),
        sa.Column("details", sa.LargeBinary(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["members.id"],
            name=op.f("fk_upload_links_member_id_members"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upload_links")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_upload_links_token_hash")),
    )
    op.create_index("ix_upload_links_expires_at", "upload_links", ["expires_at"], unique=False)
    op.create_table(
        "upload_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("link_id", sa.UUID(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("attachment_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["link_id"],
            ["upload_links.id"],
            name=op.f("fk_upload_files_link_id_upload_links"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upload_files")),
    )
    op.create_index("ix_upload_files_link_id", "upload_files", ["link_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_upload_files_link_id", table_name="upload_files")
    op.drop_table("upload_files")
    op.drop_index("ix_upload_links_expires_at", table_name="upload_links")
    op.drop_table("upload_links")
