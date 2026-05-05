"""marschbefehl fields

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('convoys', sa.Column('lage', sa.Text(), nullable=True))
    op.add_column('convoys', sa.Column('auftrag', sa.Text(), nullable=True))
    op.add_column('convoys', sa.Column('marschform', sa.String(50), nullable=True))
    op.add_column('convoys', sa.Column('ablaufpunkt', sa.String(200), nullable=True))
    op.add_column('convoys', sa.Column('ablaufzeit', sa.DateTime(timezone=True), nullable=True))
    op.add_column('convoys', sa.Column('ablaufführer', sa.String(100), nullable=True))
    op.add_column('convoys', sa.Column('versorgung', sa.Text(), nullable=True))
    op.add_column('convoys', sa.Column('funkgruppe', sa.String(100), nullable=True))
    op.add_column('convoys', sa.Column('anlagen', sa.Text(), nullable=True))

    op.add_column('convoy_vehicles', sa.Column('sonderfunktion', sa.String(50), nullable=True))
    op.add_column('convoy_vehicles', sa.Column('mobile_phone', sa.String(30), nullable=True))

    # Correct speed defaults (existing rows keep old values; new rows get new defaults via model)
    op.execute("UPDATE convoys SET speed_urban_kmh = 40 WHERE speed_urban_kmh = 50")
    op.execute("UPDATE convoys SET speed_rural_kmh = 65 WHERE speed_rural_kmh = 80")


def downgrade() -> None:
    op.drop_column('convoys', 'lage')
    op.drop_column('convoys', 'auftrag')
    op.drop_column('convoys', 'marschform')
    op.drop_column('convoys', 'ablaufpunkt')
    op.drop_column('convoys', 'ablaufzeit')
    op.drop_column('convoys', 'ablaufführer')
    op.drop_column('convoys', 'versorgung')
    op.drop_column('convoys', 'funkgruppe')
    op.drop_column('convoys', 'anlagen')
    op.drop_column('convoy_vehicles', 'sonderfunktion')
    op.drop_column('convoy_vehicles', 'mobile_phone')
