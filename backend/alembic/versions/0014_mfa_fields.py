"""add mfa fields to users

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-27

Add mfa_secret (nullable) and mfa_enabled (bool, default false) to users.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_columns = [c["name"] for c in inspector.get_columns("users")]

    if "mfa_secret" not in existing_columns:
        op.add_column(
            "users",
            sa.Column("mfa_secret", sa.String(64), nullable=True),
        )
    if "mfa_enabled" not in existing_columns:
        op.add_column(
            "users",
            sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default="false"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    existing_columns = [c["name"] for c in inspector.get_columns("users")]

    if "mfa_enabled" in existing_columns:
        op.drop_column("users", "mfa_enabled")
    if "mfa_secret" in existing_columns:
        op.drop_column("users", "mfa_secret")
