"""Aktionsseite: Absendernamen abschaltbar.

Die Karte des Bots nennt den Absender („von Jonas“), damit die Presse
nachfragen kann. Wer das nicht will, schaltet es je Seite ab: dann speichert
ConvoyPlan den Namen gar nicht erst, und vorhandene Namen der Seite werden
beim Abschalten gelöscht (Plan § 14.4).

Standard ``true`` — so verhielt es sich bisher.

Revision ID: 0071
Revises: 0070
Create Date: 2026-10-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "public_trackers",
        sa.Column("show_sender", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("public_trackers", "show_sender")
