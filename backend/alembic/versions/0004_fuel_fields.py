"""fuel fields for vehicles

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('vehicles', sa.Column('tank_capacity_l', sa.Float(), nullable=True))
    op.add_column('vehicles', sa.Column('fuel_consumption_l100km', sa.Float(), nullable=True))
    op.add_column('vehicles', sa.Column('current_fuel_l', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('vehicles', 'tank_capacity_l')
    op.drop_column('vehicles', 'fuel_consumption_l100km')
    op.drop_column('vehicles', 'current_fuel_l')
