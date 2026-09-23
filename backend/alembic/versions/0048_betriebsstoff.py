"""Betriebsstofflage je Fahrzeug im Marschverband.

Drei Spalten und ein Zeitstempel auf ``convoy_vehicles``: Verbrauch
(l/100 km), Tankvolumen (l) und Füllstand (%), so wie die Besatzung sie
unterwegs meldet — über den Fahrer-Link der Companion-App.

Alle Spalten sind **nullable ohne Vorgabewert**, aus demselben Grund wie bei
der Stärke (``0043``): Ein ``server_default = 0`` meldete für jedes bestehende
Fahrzeug einen leeren Tank. Liter im Tank und Reichweite bekommen keine
Spalte, sie werden gerechnet (``app/services/betriebsstoff.py``).

Revision ID: 0048
Revises: 0047
Create Date: 2026-09-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("convoy_vehicles", sa.Column("betriebsstoff_verbrauch", sa.Float(), nullable=True))
    op.add_column("convoy_vehicles", sa.Column("betriebsstoff_tank", sa.Integer(), nullable=True))
    op.add_column("convoy_vehicles", sa.Column("betriebsstoff_fuellstand", sa.Integer(), nullable=True))
    op.add_column(
        "convoy_vehicles",
        sa.Column("betriebsstoff_gemeldet_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("convoy_vehicles", "betriebsstoff_gemeldet_at")
    op.drop_column("convoy_vehicles", "betriebsstoff_fuellstand")
    op.drop_column("convoy_vehicles", "betriebsstoff_tank")
    op.drop_column("convoy_vehicles", "betriebsstoff_verbrauch")
