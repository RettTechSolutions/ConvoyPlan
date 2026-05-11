"""add kanalwechsel column to routes

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = [col["name"] for col in inspector.get_columns("routes")]
    if "kanalwechsel" not in existing:
        op.add_column("routes", sa.Column("kanalwechsel", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("routes", "kanalwechsel")
