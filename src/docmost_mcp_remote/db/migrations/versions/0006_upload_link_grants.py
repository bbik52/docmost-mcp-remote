"""Upload links belong to the grant that made them.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("upload_links", sa.Column("grant_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_upload_links_grant_id_grants"),
        "upload_links",
        "grants",
        ["grant_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_upload_links_grant_id_grants"), "upload_links", type_="foreignkey")
    op.drop_column("upload_links", "grant_id")
