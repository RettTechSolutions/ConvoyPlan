"""Störungen eines Trackers während der Fahrt (``unterbrochen_ab``, ``gps_gestoert_ab``).

Während der Fahrt erwartet die Instanz alle ``buendel_s`` ein Bündel. Bleiben zwei
aus, zeigt sie „Verbindung unterbrochen"; kommen Bündel, aber keine plausiblen
Fixes, „GPS gestört" (``services/ortungsgeraet.py``, Protokoll im Tracker-Repo,
„Verbindung unterbrochen"). Nullable ohne Vorgabe: NULL heißt, die Instanz
erwartet nichts — so stehen alle Geräte bis zu ihrem nächsten Bündel.

Revision ID: 0066
Revises: 0065
Create Date: 2026-10-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ortungsgeraete", sa.Column("unterbrochen_ab", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ortungsgeraete", sa.Column("gps_gestoert_ab", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("ortungsgeraete", "gps_gestoert_ab")
    op.drop_column("ortungsgeraete", "unterbrochen_ab")
