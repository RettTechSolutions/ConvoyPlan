"""V2 und V3 Features

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
import geoalchemy2
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # V2: Organisationen
    op.create_table(
        "organizations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "user_organizations",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(30), nullable=False, server_default="beobachter"),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "organization_id"),
    )

    # V2: Convoy-Erweiterungen
    op.add_column("convoys", sa.Column("organization_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_convoy_organization", "convoys", "organizations", ["organization_id"], ["id"], ondelete="SET NULL")

    op.add_column("convoys", sa.Column("parent_convoy_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_convoy_parent", "convoys", "convoys", ["parent_convoy_id"], ["id"], ondelete="SET NULL", use_alter=True)

    # V3: Fahrzeugstatus im Konvoi
    op.add_column("convoy_vehicles", sa.Column("vehicle_status", sa.String(30), nullable=False, server_default="planned"))

    # V2: Technische Halte - Haltegrund
    op.add_column("waypoints", sa.Column("halt_purpose", sa.String(50), nullable=True))

    # V3: Live-Tracking Positionen
    op.create_table(
        "vehicle_positions",
        sa.Column("convoy_id", sa.UUID(), nullable=False),
        sa.Column("vehicle_id", sa.UUID(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("speed_kmh", sa.Float(), nullable=True),
        sa.Column("heading", sa.Float(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["convoy_id"], ["convoys.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("convoy_id", "vehicle_id"),
    )

    # V3: Lagedaten (GeoJSON-Layer)
    op.create_table(
        "lage_layers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("convoy_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("geojson_data", sa.JSON(), nullable=False),
        sa.Column("color", sa.String(20), nullable=False, server_default="#e74c3c"),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["convoy_id"], ["convoys.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("lage_layers")
    op.drop_table("vehicle_positions")
    op.drop_column("waypoints", "halt_purpose")
    op.drop_column("convoy_vehicles", "vehicle_status")
    op.drop_constraint("fk_convoy_parent", "convoys", type_="foreignkey")
    op.drop_column("convoys", "parent_convoy_id")
    op.drop_constraint("fk_convoy_organization", "convoys", type_="foreignkey")
    op.drop_column("convoys", "organization_id")
    op.drop_table("user_organizations")
    op.drop_table("organizations")
