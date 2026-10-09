"""Positionsquelle: Tracker vor Telefon, von der Führung übersteuerbar (services/positionsquelle.py).

- ``convoy_vehicles.tracker_uebersteuert_at`` / ``_von``: die Führung hat
  entschieden, dass für dieses Fahrzeug im Konvoi das Telefon gilt und nicht
  der Tracker. In der Datenbank, weil ein Neustart die Entscheidung nicht
  zurücknehmen darf. NULL heißt: der Tracker hat Vorrang, solange er sendet.
- ``vehicle_positions.quelle``: woher die aktuelle Position kam (``tracker``),
  NULL für Fahrer-Link und App — damit die Karte nach dem Laden weiß, was sie
  als Tracker-Position kennzeichnet.

Revision ID: 0058
Revises: 0057
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "convoy_vehicles",
        sa.Column("tracker_uebersteuert_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("convoy_vehicles", sa.Column("tracker_uebersteuert_von", sa.String(120), nullable=True))
    op.add_column("vehicle_positions", sa.Column("quelle", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("vehicle_positions", "quelle")
    op.drop_column("convoy_vehicles", "tracker_uebersteuert_von")
    op.drop_column("convoy_vehicles", "tracker_uebersteuert_at")
