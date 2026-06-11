"""Add is_demo flag to users and organizations for ephemeral demo sessions.

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_cols = [c["name"] for c in inspector.get_columns("users")]
    if "is_demo" not in user_cols:
        op.add_column(
            "users",
            sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="false"),
        )

    org_cols = [c["name"] for c in inspector.get_columns("organizations")]
    if "is_demo" not in org_cols:
        op.add_column(
            "organizations",
            sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="false"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    org_cols = [c["name"] for c in inspector.get_columns("organizations")]
    if "is_demo" in org_cols:
        op.drop_column("organizations", "is_demo")

    user_cols = [c["name"] for c in inspector.get_columns("users")]
    if "is_demo" in user_cols:
        op.drop_column("users", "is_demo")
