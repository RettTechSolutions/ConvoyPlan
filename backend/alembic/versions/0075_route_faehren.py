"""Fährabschnitte einer Route (services/faehre.py).

Auf See vergeht Reisezeit, aber keine Lenkzeit, und die Überfahrt ist selbst
ein Halt. Die Abschnitte werden bei der Berechnung aus GraphHoppers
``road_environment`` und ``time`` gelesen und gespeichert, weil Halteempfehlung,
Zeitplan und Ausdruck sie später brauchen und die Path-Details dann nicht mehr
da sind — wie bei den Durchfahrtshöhen (0055).

Nullable ohne Vorgabewert: ``None`` heißt „nicht ermittelt" (Route von vor
dieser Migration, Import, Graph ohne ``road_environment``), ``[]`` heißt „keine
Fähre". Bei ``None`` rechnet alles wie bisher.

Revision ID: 0075
Revises: 0074
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("routes", sa.Column("faehren", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("routes", "faehren")
