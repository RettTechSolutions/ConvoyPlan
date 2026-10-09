"""Meldungen selbst gehosteter Instanzen an den Hersteller weiterleiten.

- ``weiterleitung`` / ``weitergeleitet_at``: Zustand auf der meldenden
  Instanz. Bestehende Zeilen bleiben NULL und werden **nicht** nachgeschickt —
  ihre Melder haben einen Dialog gesehen, der nur den Betreiber der Instanz
  als Empfänger nannte.
- ``herkunft_instanz`` / ``herkunft_id`` / ``herkunft_url``: auf dem
  Hosting-Server, woher eine weitergeleitete Meldung stammt. Eindeutig über
  Instanz und Kennung, damit eine wiederholte Zustellung keine Dublette ergibt.

Revision ID: 0059
Revises: 0058
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feedback_reports", sa.Column("weiterleitung", sa.String(16), nullable=True))
    op.add_column("feedback_reports", sa.Column("weitergeleitet_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("feedback_reports", sa.Column("herkunft_instanz", sa.String(64), nullable=True))
    op.add_column("feedback_reports", sa.Column("herkunft_id", UUID(as_uuid=True), nullable=True))
    op.add_column("feedback_reports", sa.Column("herkunft_url", sa.String(255), nullable=True))
    op.create_index("ix_feedback_reports_weiterleitung", "feedback_reports", ["weiterleitung"])
    op.create_unique_constraint(
        "uq_feedback_herkunft", "feedback_reports", ["herkunft_instanz", "herkunft_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_feedback_herkunft", "feedback_reports", type_="unique")
    op.drop_index("ix_feedback_reports_weiterleitung", table_name="feedback_reports")
    op.drop_column("feedback_reports", "herkunft_url")
    op.drop_column("feedback_reports", "herkunft_id")
    op.drop_column("feedback_reports", "herkunft_instanz")
    op.drop_column("feedback_reports", "weitergeleitet_at")
    op.drop_column("feedback_reports", "weiterleitung")
