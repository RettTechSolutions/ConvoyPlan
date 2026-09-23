"""Quittung eines Alarms durch die Führung.

Zwei Spalten auf ``convoy_vehicles``: wann der laufende Alarm (Techn. Halt,
Ausfall) quittiert wurde und von wem — als Anzeigetext, nicht als Verweis:
Quittieren kann ein angemeldeter Nutzer ebenso wie ein Gerät am Fahrer-Link,
das nur ein Fahrzeug kennt.

Die Quittung gehört zu **einem** Alarm. Jeder neue Status setzt sie zurück
(``app/services/alarm_quittung.py``, ``zuruecksetzen``); welcher Alarm gemeint
ist, sagt ``status_changed_at``.

Revision ID: 0049
Revises: 0048
Create Date: 2026-09-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "convoy_vehicles",
        sa.Column("alarm_quittiert_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "convoy_vehicles", sa.Column("alarm_quittiert_von", sa.String(120), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("convoy_vehicles", "alarm_quittiert_von")
    op.drop_column("convoy_vehicles", "alarm_quittiert_at")
