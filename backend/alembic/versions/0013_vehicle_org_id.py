"""vehicle org_id

Revision ID: 0013_vehicle_org_id
Revises: 0012_org_slug
Create Date: 2026-05-27

Add org_id to vehicles for direct org-scoping.
Existing vehicles get org_id=NULL (they'll be invisible until reassigned,
but in practice the DB is nearly empty at this stage).
"""
from alembic import op
import sqlalchemy as sa
import uuid

revision = "0013_vehicle_org_id"
down_revision = "0012_org_slug"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vehicles",
        sa.Column(
            "org_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_vehicles_org_id", "vehicles", ["org_id"])


def downgrade() -> None:
    op.drop_index("ix_vehicles_org_id", table_name="vehicles")
    op.drop_column("vehicles", "org_id")
