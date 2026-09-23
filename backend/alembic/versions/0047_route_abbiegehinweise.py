"""Abbiegehinweise der Route fürs Roadbook.

GraphHopper wurde bisher mit ``instructions=false`` gefragt, es gab also nichts
zu drucken. Gespeichert wird bei der Berechnung, nicht beim Druck: ein erneuter
Aufruf von GraphHopper beim Export könnte eine andere Route liefern als die, die
auf der Karte und im Zeitplan steht — nach einem Kartenupdate oder mit geänderten
Fahrzeughöhen. Der Ausdruck muss zur geplanten Route passen.

Nullable ohne Vorgabewert: bestehende Routen haben keine Hinweise, und eine
leere Liste sähe aus wie „geradeaus bis zum Ziel". Nach der nächsten
Berechnung sind sie da.

Revision ID: 0047
Revises: 0046
Create Date: 2026-09-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("routes", sa.Column("instructions", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("routes", "instructions")
