"""Gewichtsgrenzen entlang der Route (services/gewichtsgrenzen.py).

Wie ``durchfahrtshoehen`` (0055): bei der Berechnung festgehalten, damit
Planungsansicht und Marschbefehl zur geplanten Route passen. NULL heißt „nicht
ermittelt" — Route von vorher, importiert, oder der Graph kannte ``max_weight``
noch nicht (GraphHopper-Container nicht neu gebaut). Eine leere Liste heißt
„keine bekannte Grenze".

Revision ID: 0059
Revises: 0058
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("routes", sa.Column("gewichtsgrenzen", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("routes", "gewichtsgrenzen")
