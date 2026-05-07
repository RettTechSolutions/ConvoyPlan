import sqlalchemy as sa
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('vehicles', sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('vehicles', 'order_index')
