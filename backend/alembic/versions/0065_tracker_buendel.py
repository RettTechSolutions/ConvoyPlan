"""Wie oft die Tracker einer Organisation senden (``organizations.tracker_buendel_s``).

Der Org-Admin wählt den Bündeltakt unter Tracker → Sendetakt, abgewogen gegen
das Datenvolumen. Nullable ohne Vorgabe: NULL heißt Standard, und der steht an
einer Stelle (``services/ortungsgeraet.TAKT``), nicht in einem
``server_default``.

Revision ID: 0065
Revises: 0064
Create Date: 2026-10-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("tracker_buendel_s", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "tracker_buendel_s")
