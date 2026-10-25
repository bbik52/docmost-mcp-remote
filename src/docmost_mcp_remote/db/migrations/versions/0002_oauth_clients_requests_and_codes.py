"""OAuth clients, authorization requests and codes.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("info", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("client_id", name=op.f("pk_oauth_clients")),
    )
    op.create_table(
        "oauth_requests",
        sa.Column("id_hash", sa.LargeBinary(), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("params", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.client_id"],
            name=op.f("fk_oauth_requests_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id_hash", name=op.f("pk_oauth_requests")),
    )
    op.create_table(
        "oauth_codes",
        sa.Column("code_hash", sa.LargeBinary(), nullable=False),
        sa.Column("grant_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False),
        sa.Column("scopes", sa.String(length=100), nullable=False),
        sa.Column("resource", sa.String(length=500), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["grants.id"],
            name=op.f("fk_oauth_codes_grant_id_grants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("code_hash", name=op.f("pk_oauth_codes")),
    )
    op.add_column("tokens", sa.Column("resource", sa.String(length=500), nullable=True))
    op.add_column("tokens", sa.Column("scopes", sa.String(length=100), nullable=True))
    op.add_column("tokens", sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tokens", "replaced_at")
    op.drop_column("tokens", "scopes")
    op.drop_column("tokens", "resource")
    op.drop_table("oauth_codes")
    op.drop_table("oauth_requests")
    op.drop_table("oauth_clients")
