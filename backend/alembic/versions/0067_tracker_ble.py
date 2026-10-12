"""Drei Wege ins Netz: Geräteschlüssel, Weiterleitung über BLE, letzter Weg (E14).

- ``schluessel``: der Geräteschlüssel (32 Byte), mit dem der Tracker seine Rahmen für
  die Weiterleitung über die Begleit-App signiert und die Instanz ihre Antwort. Neu bei
  jedem ``einloesen``. Verschlüsselt abgelegt (``services/crypto.py``, wie die
  MFA-Geheimnisse), NULL bei Geräten von vor dieser Fassung — die bekommen ihn beim
  nächsten direkten ``hallo``.
- ``ble_seq``: die zuletzt angenommene ``seq`` eines weitergeleiteten Rahmens; nur
  größere werden angenommen. NULL: noch keiner seit dem letzten Schlüssel.
- ``netz``: der Weg des letzten Aufrufs (``wlan``, ``mobil``, ``ble``), damit die
  Ansicht statt Empfangsbalken das richtige Symbol zeigt.

Protokoll im Tracker-Repo (``docs/PROTOKOLL.md``, „Drei Wege ins Netz").

Revision ID: 0067
Revises: 0066
Create Date: 2026-10-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ortungsgeraete", sa.Column("schluessel", sa.String(200), nullable=True))
    op.add_column("ortungsgeraete", sa.Column("ble_seq", sa.BigInteger(), nullable=True))
    op.add_column("ortungsgeraete", sa.Column("netz", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("ortungsgeraete", "netz")
    op.drop_column("ortungsgeraete", "ble_seq")
    op.drop_column("ortungsgeraete", "schluessel")
