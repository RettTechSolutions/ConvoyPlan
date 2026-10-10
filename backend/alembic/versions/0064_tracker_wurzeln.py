"""Welche eigenen Wurzeln ein Tracker hat (``ortungsgeraete.wurzeln_sha256``).

Die Instanz verteilt Wurzelzertifikate an ihre Tracker (E12 im Tracker-Plan,
``services/tracker_wurzeln.py``) und muss wissen, welches Gerät das gewünschte
Bündel schon übernommen hat. Nullable ohne Vorgabe: Geräte melden den
Fingerabdruck mit dem nächsten ``hallo``, ältere Firmware nie.

Revision ID: 0064
Revises: 0063
Create Date: 2026-10-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ortungsgeraete", sa.Column("wurzeln_sha256", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("ortungsgeraete", "wurzeln_sha256")
