"""add user roles

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = [col["name"] for col in inspector.get_columns("users")]
    if "is_active" not in existing:
        op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"))
    if "is_superadmin" not in existing:
        op.add_column("users", sa.Column("is_superadmin", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("users", "is_superadmin")
    op.drop_column("users", "is_active")
