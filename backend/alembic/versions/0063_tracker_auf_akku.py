"""Tracker: seit wann ohne Bordnetz (services/ortungsgeraet.py, ``auf_akku_seit``).

``ortungsgeraete.auf_akku_seit``: Zeitpunkt des Wechsels von Bordnetz auf Akku,
damit die Oberfläche „auf Akku seit 3 Tagen" zeigen kann statt nur des letzten
Werts von ``extern``. NULL am Bordnetz und für jedes Gerät, das seit dem Update
noch nichts gemeldet hat.

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
    op.add_column("ortungsgeraete", sa.Column("auf_akku_seit", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("ortungsgeraete", "auf_akku_seit")
