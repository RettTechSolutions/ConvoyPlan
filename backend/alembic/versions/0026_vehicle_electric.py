"""electric vehicle support

Adds propulsion type and battery fields so e-vehicles can be planned alongside
combustion vehicles (range analysis, charging-stop recommendation).

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa

revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'vehicles',
        sa.Column('propulsion', sa.String(length=20), nullable=False, server_default='combustion'),
    )
    op.add_column('vehicles', sa.Column('battery_capacity_kwh', sa.Float(), nullable=True))
    op.add_column('vehicles', sa.Column('consumption_kwh_100km', sa.Float(), nullable=True))
    op.add_column('vehicles', sa.Column('current_charge_kwh', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('vehicles', 'current_charge_kwh')
    op.drop_column('vehicles', 'consumption_kwh_100km')
    op.drop_column('vehicles', 'battery_capacity_kwh')
    op.drop_column('vehicles', 'propulsion')
