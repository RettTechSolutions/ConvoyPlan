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
from sqlalchemy.engine.reflection import Inspector

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    existing_columns = [c["name"] for c in inspector.get_columns("vehicles")]
    if "org_id" not in existing_columns:
        op.add_column(
            "vehicles",
            sa.Column("org_id", sa.UUID(), nullable=True),
        )
        op.create_foreign_key(
            "fk_vehicles_org_id",
            "vehicles", "organizations",
            ["org_id"], ["id"],
            ondelete="CASCADE",
        )

    existing_indexes = [idx["name"] for idx in inspector.get_indexes("vehicles")]
    if "ix_vehicles_org_id" not in existing_indexes:
        op.create_index("ix_vehicles_org_id", "vehicles", ["org_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    existing_indexes = [idx["name"] for idx in inspector.get_indexes("vehicles")]
    if "ix_vehicles_org_id" in existing_indexes:
        op.drop_index("ix_vehicles_org_id", table_name="vehicles")

    existing_columns = [c["name"] for c in inspector.get_columns("vehicles")]
    if "org_id" in existing_columns:
        op.drop_constraint("fk_vehicles_org_id", "vehicles", type_="foreignkey")
        op.drop_column("vehicles", "org_id")
