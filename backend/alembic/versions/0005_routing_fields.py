"""routing fields for convoy

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('convoys', sa.Column('road_preference', sa.String(20), nullable=False, server_default='schnell'))
    op.add_column('convoys', sa.Column('spacing_urban_m', sa.Integer(), nullable=False, server_default='15'))
    op.add_column('convoys', sa.Column('spacing_rural_m', sa.Integer(), nullable=False, server_default='50'))
    op.add_column('convoys', sa.Column('spacing_motorway_m', sa.Integer(), nullable=False, server_default='100'))


def downgrade() -> None:
    op.drop_column('convoys', 'road_preference')
    op.drop_column('convoys', 'spacing_urban_m')
    op.drop_column('convoys', 'spacing_rural_m')
    op.drop_column('convoys', 'spacing_motorway_m')
