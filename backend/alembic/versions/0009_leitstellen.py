"""add leitstellen table

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-11
"""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "leitstellen",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("anrufgruppe", sa.String(50), nullable=False),
        sa.Column("zusatz_kanaele", sa.JSON(), nullable=True),
        sa.Column("geometry", Geometry("GEOMETRY", srid=4326), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("leitstellen")
