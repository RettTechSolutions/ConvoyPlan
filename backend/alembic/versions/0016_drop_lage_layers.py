"""drop lage_layers table

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("lage_layers")


def downgrade() -> None:
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
