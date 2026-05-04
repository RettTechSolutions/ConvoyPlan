"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
import geoalchemy2
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "vehicles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("callsign", sa.String(50), nullable=True),
        sa.Column("license_plate", sa.String(20), nullable=True),
        sa.Column("height_cm", sa.Integer(), nullable=True),
        sa.Column("weight_kg", sa.Integer(), nullable=True),
        sa.Column("length_cm", sa.Integer(), nullable=True),
        sa.Column("convoy_role", sa.String(50), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "convoys",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("organization", sa.String(100), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_point", geoalchemy2.types.Geometry("POINT", srid=4326), nullable=True),
        sa.Column("end_point", geoalchemy2.types.Geometry("POINT", srid=4326), nullable=True),
        sa.Column("speed_urban_kmh", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("speed_rural_kmh", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("status", sa.String(20), nullable=False, server_default="planning"),
        sa.Column("share_token", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("share_token"),
    )
    op.create_index("ix_convoys_share_token", "convoys", ["share_token"])

    op.create_table(
        "convoy_vehicles",
        sa.Column("convoy_id", sa.UUID(), nullable=False),
        sa.Column("vehicle_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["convoy_id"], ["convoys.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("convoy_id", "vehicle_id"),
    )

    op.create_table(
        "waypoints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("convoy_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("type", sa.String(30), nullable=False, server_default="waypoint"),
        sa.Column("location", geoalchemy2.types.Geometry("POINT", srid=4326), nullable=True),
        sa.Column("planned_arrival", sa.DateTime(timezone=True), nullable=True),
        sa.Column("planned_departure", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hold_duration_min", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["convoy_id"], ["convoys.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "routes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("convoy_id", sa.UUID(), nullable=False),
        sa.Column("geometry", geoalchemy2.types.Geometry("LINESTRING", srid=4326), nullable=True),
        sa.Column("distance_m", sa.Integer(), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column("routing_params", sa.JSON(), nullable=True),
        sa.Column("gpx_data", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["convoy_id"], ["convoys.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("convoy_id"),
    )


def downgrade() -> None:
    op.drop_table("routes")
    op.drop_table("waypoints")
    op.drop_table("convoy_vehicles")
    op.drop_table("convoys")
    op.drop_table("vehicles")
    op.drop_table("users")
