"""user first/last name

Adds optional Vorname/Nachname to users so invitations and password emails
can address the recipient personally.

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa

revision = '0027'
down_revision = '0026'
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = [c["name"] for c in inspector.get_columns("users")]
    if "first_name" not in existing:
        op.add_column("users", sa.Column("first_name", sa.String(length=100), nullable=True))
    if "last_name" not in existing:
        op.add_column("users", sa.Column("last_name", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
