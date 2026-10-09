"""Ortungsgeräte: feste Tracker im Fahrzeug (models/ortungsgeraet.py).

Ein Gerät je Fahrzeug (``vehicle_id`` eindeutig), Einmal-Code und Gerätetoken
nur als SHA-256, dazu was das Gerät zuletzt über sich gemeldet hat. Das Protokoll
steht im Repo ConvoyPlan-Tracker (``docs/PROTOKOLL.md``).

Revision ID: 0057
Revises: 0056
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ortungsgeraete",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id", sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "vehicle_id", sa.Uuid(),
            sa.ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, unique=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kanal", sa.String(20), nullable=False, server_default="stable"),
        sa.Column("aktiv", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("code_hash", sa.String(64), nullable=True),
        sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("eingerichtet_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hardware_id", sa.String(64), nullable=True),
        sa.Column("hardware", sa.String(40), nullable=True),
        sa.Column("firmware", sa.String(40), nullable=True),
        sa.Column("zuletzt_gesehen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("akku_prozent", sa.Integer(), nullable=True),
        sa.Column("extern", sa.Boolean(), nullable=True),
        sa.Column("signal_dbm", sa.Integer(), nullable=True),
        sa.Column("update_version", sa.String(40), nullable=True),
        sa.Column("update_ergebnis", sa.String(20), nullable=True),
        sa.Column("update_meldung", sa.String(200), nullable=True),
        sa.Column("update_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    op.create_index("ix_ortungsgeraete_organization_id", "ortungsgeraete", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_ortungsgeraete_organization_id", table_name="ortungsgeraete")
    op.drop_table("ortungsgeraete")
