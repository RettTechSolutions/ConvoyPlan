"""Seit wann ein Tracker auf Akku läuft (``ortungsgeraete.akku_seit``).

Die Instanz kannte nur den letzten Wert von ``extern``. Für den Hinweis „auf Akku
seit 3 Tagen" braucht es den Zeitpunkt des Wechsels. Nullable ohne Vorgabe:
bestehende Geräte bekommen ihn mit der nächsten Meldung ``extern=false``.

Revision ID: 0063
Revises: 0062
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ortungsgeraete", sa.Column("akku_seit", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("ortungsgeraete", "akku_seit")
