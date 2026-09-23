"""Gemeldeter Füllstand je Fahrzeug im Marschverband.

Die Besatzung meldet unterwegs, wie voll Tank oder Akku ist — in Prozent, so
wie sie es ablesen kann. Die Meldung gehört zur Zeile in ``convoy_vehicles``
und nicht zum Fahrzeug: Ein öffentlicher Fahrer-Link darf die Stammdaten der
Organisation nicht umschreiben, und der eingetragene Füllstand am Fahrzeug
bleibt, was er ist — der Stand bei der Planung.

Nullable ohne Vorgabewert: NULL heißt „nicht gemeldet", 0 heißt „leer".

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
    op.add_column(
        "convoy_vehicles", sa.Column("fuellstand_ist_prozent", sa.Integer(), nullable=True)
    )
    op.add_column(
        "convoy_vehicles",
        sa.Column("fuellstand_gemeldet_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("convoy_vehicles", "fuellstand_gemeldet_at")
    op.drop_column("convoy_vehicles", "fuellstand_ist_prozent")
