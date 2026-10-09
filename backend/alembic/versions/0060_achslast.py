"""Größte Achslast als Fahrzeugfeld (``vehicles.axle_load_kg``).

Gegenstück zu ``max_axle_load`` im Routing-Graphen (Zeichen 263, OSM
``maxaxleload``): gesperrt wird mit der größten Achslast im Verband, wie bei
Höhe und Gewicht. Nullable — ohne Angabe sperrt das Fahrzeug nichts.

Revision ID: 0060
Revises: 0059
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vehicles", sa.Column("axle_load_kg", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("vehicles", "axle_load_kg")
