"""Öffentliche Aktionsseite: Seiten je Organisation und Positionsverlauf.

Drei Tabellen. ``public_trackers`` ist eine Aktionsseite, ``public_tracker_
convoys`` ordnet ihr Konvois mit öffentlichem Namen zu. ``vehicle_position_
trail`` ist der Positionsverlauf — ``vehicle_positions`` hält nur die letzte
Position je Fahrzeug, und „wo war der Konvoi vor zwei Stunden" lässt sich
daraus nicht beantworten. Aufgezeichnet wird nur für Konvois an einer aktiven
Aktionsseite (``services/positionsverlauf.py``); bestehende Daten gibt es
dafür nicht, die Migration legt nur an.

Revision ID: 0052
Revises: 0051
Create Date: 2026-10-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "public_trackers",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("slug", sa.String(32), nullable=False, unique=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("subtitle", sa.String(300), nullable=True),
        sa.Column("facts", sa.Text(), nullable=True),
        sa.Column("theme", sa.String(20), nullable=False, server_default="neutral"),
        sa.Column("delay_minutes", sa.Integer(), nullable=False),
        sa.Column("show_destination", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("fetch_token_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_by_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # Die Untergrenze steht auch hier und nicht nur im Schema: eine Seite
        # mit weniger als einer Stunde Verzögerung soll es nicht geben, auch
        # nicht über einen Weg, der am Schema vorbeigeht.
        sa.CheckConstraint("delay_minutes >= 60", name="ck_public_trackers_delay_min"),
    )
    op.create_table(
        "public_tracker_convoys",
        sa.Column(
            "tracker_id",
            sa.UUID(),
            sa.ForeignKey("public_trackers.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "convoy_id",
            sa.UUID(),
            sa.ForeignKey("convoys.id", ondelete="CASCADE"),
            primary_key=True,
            index=True,
        ),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("destination_label", sa.String(100), nullable=True),
        sa.Column("color", sa.String(9), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "vehicle_position_trail",
        sa.Column(
            "convoy_id",
            sa.UUID(),
            sa.ForeignKey("convoys.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "vehicle_id",
            sa.UUID(),
            sa.ForeignKey("vehicles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_vehicle_position_trail_convoy_time",
        "vehicle_position_trail",
        ["convoy_id", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_vehicle_position_trail_convoy_time", table_name="vehicle_position_trail")
    op.drop_table("vehicle_position_trail")
    op.drop_table("public_tracker_convoys")
    op.drop_table("public_trackers")
