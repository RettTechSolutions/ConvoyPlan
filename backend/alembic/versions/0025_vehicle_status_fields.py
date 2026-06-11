"""convoy vehicle status communication fields

Adds sub-level / note / timestamp columns used by the live-tracking status
panel (technical halt urgency, breakdown severity, free-text note).

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa

revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('convoy_vehicles', sa.Column('status_level', sa.String(length=20), nullable=True))
    op.add_column('convoy_vehicles', sa.Column('status_note', sa.String(length=200), nullable=True))
    op.add_column('convoy_vehicles', sa.Column('status_changed_at', sa.DateTime(timezone=True), nullable=True))
    # Legacy "delayed" status is no longer part of the picker — map it to en_route.
    op.execute("UPDATE convoy_vehicles SET vehicle_status = 'en_route' WHERE vehicle_status = 'delayed'")


def downgrade() -> None:
    op.drop_column('convoy_vehicles', 'status_changed_at')
    op.drop_column('convoy_vehicles', 'status_note')
    op.drop_column('convoy_vehicles', 'status_level')
