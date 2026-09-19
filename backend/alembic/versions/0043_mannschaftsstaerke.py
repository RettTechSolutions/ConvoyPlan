"""Mannschaftsstärke je Fahrzeug im Marschverband.

Sechs Zahlenspalten und ein Zeitstempel auf ``convoy_vehicles``: das Soll aus
der Planung, das Ist aus der Meldung unterwegs, jeweils nach Führern,
Unterführern und Mannschaften getrennt (Notation ``0/1/8//9``).

Alle Spalten sind **nullable ohne Vorgabewert**. Ein ``server_default = 0``
hätte jeden bestehenden Marschverband so aussehen lassen, als sei jedes
Fahrzeug unbesetzt gemeldet worden — und genau diese Verwechslung von „nicht
gemeldet" mit „niemand an Bord" soll die Anzeige ausschließen.

Die Gesamtstärke bekommt keine Spalte: sie ist die Summe der drei Zahlen und
wird bei jedem Lesen gerechnet (``app/services/staerke.py``). Gespeichert
würde sie irgendwann von ihren Summanden abweichen.

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

_SPALTEN = (
    "staerke_soll_fuehrer",
    "staerke_soll_unterfuehrer",
    "staerke_soll_mannschaften",
    "staerke_ist_fuehrer",
    "staerke_ist_unterfuehrer",
    "staerke_ist_mannschaften",
)


def upgrade() -> None:
    for spalte in _SPALTEN:
        op.add_column("convoy_vehicles", sa.Column(spalte, sa.Integer(), nullable=True))
    op.add_column(
        "convoy_vehicles",
        sa.Column("staerke_gemeldet_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("convoy_vehicles", "staerke_gemeldet_at")
    for spalte in reversed(_SPALTEN):
        op.drop_column("convoy_vehicles", spalte)
