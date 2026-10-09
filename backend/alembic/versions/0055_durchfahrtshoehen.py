"""Höhenbeschränkungen entlang der Route (services/durchfahrtshoehe.py).

Gesperrt hat das Routing schon immer — still. Die Spalte hält fest, unter welchen
Höhenbeschränkungen die berechnete Route hindurchführt, damit Planungsansicht
und Marschbefehl darauf hinweisen. Gespeichert bei der Berechnung, aus demselben
Grund wie die Abbiegehinweise (0047): der Ausdruck muss zur geplanten Route
passen, nicht zu einer neuen Anfrage beim Export.

Nullable ohne Vorgabewert: eine leere Liste hieße „keine Beschränkung auf der
Strecke", und das weiß bei bestehenden Routen niemand. Nach der nächsten
Berechnung ist sie da.

Revision ID: 0055
Revises: 0054
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("routes", sa.Column("durchfahrtshoehen", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("routes", "durchfahrtshoehen")
