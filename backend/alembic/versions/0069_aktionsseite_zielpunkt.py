"""Aktionsseite: eigener Zielpunkt je Konvoi.

Bisher zeigte die Seite als Ziel den letzten Wegpunkt. Der ist oft nicht das
Ziel: Ein Hilfskonvoi nach Albanien plant bis zur Fähre in Bari, weiter geht
es übers Meer, und Shkodra stand nur als Text da. Jetzt lässt sich das Ziel
je Konvoi eigens setzen; ohne Angabe bleibt es beim letzten Wegpunkt.

Beide Spalten oder keine — ein halber Punkt ist kein Ort.

Revision ID: 0069
Revises: 0068
Create Date: 2026-10-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("public_tracker_convoys", sa.Column("destination_lat", sa.Float(), nullable=True))
    op.add_column("public_tracker_convoys", sa.Column("destination_lon", sa.Float(), nullable=True))
    op.create_check_constraint(
        "ck_public_tracker_convoys_zielpunkt",
        "public_tracker_convoys",
        "(destination_lat IS NULL) = (destination_lon IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_public_tracker_convoys_zielpunkt", "public_tracker_convoys", type_="check")
    op.drop_column("public_tracker_convoys", "destination_lon")
    op.drop_column("public_tracker_convoys", "destination_lat")
