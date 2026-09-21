"""Regelbesatzung als Stammdatum am Fahrzeug.

Dieselben drei Zahlen wie das Soll in ``convoy_vehicles`` (0043), nur eine
Ebene höher: am Fahrzeug steht, mit wem es üblicherweise ausrückt. Beim
Zuordnen zu einem Konvoi wird der Wert in die Planung übernommen — die Zeile
in ``convoy_vehicles`` bleibt danach eigenständig, sonst schriebe eine
Stammdatenpflege bestehende Marschbefehle um.

Nullable ohne Vorgabewert, aus demselben Grund wie in 0043: ein
``server_default = 0`` ließe jedes bestehende Fahrzeug als „unbesetzt"
dastehen, statt als „nicht angegeben".

Revision ID: 0045
Revises: 0044
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

_SPALTEN = (
    "staerke_soll_fuehrer",
    "staerke_soll_unterfuehrer",
    "staerke_soll_mannschaften",
)


def upgrade() -> None:
    for spalte in _SPALTEN:
        op.add_column("vehicles", sa.Column(spalte, sa.Integer(), nullable=True))


def downgrade() -> None:
    for spalte in reversed(_SPALTEN):
        op.drop_column("vehicles", spalte)
