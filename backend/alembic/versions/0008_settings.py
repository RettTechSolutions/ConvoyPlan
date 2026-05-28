"""add system_settings table

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "system_settings" not in inspector.get_table_names():
        op.create_table(
            "system_settings",
            sa.Column("key", sa.String(255), primary_key=True),
            sa.Column("value", sa.Text(), nullable=False, server_default=""),
        )


def downgrade() -> None:
    op.drop_table("system_settings")
