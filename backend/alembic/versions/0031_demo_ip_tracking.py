"""Add demo_created_ip / demo_created_location to organizations.

Demo sessions record the creating client's IP and a rough geo location so the
superadmin can tell which demo session belongs to which interested party.
Both columns stay NULL for regular organisations and are deleted together
with the demo org by the retention job.

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    org_cols = [c["name"] for c in inspector.get_columns("organizations")]
    if "demo_created_ip" not in org_cols:
        op.add_column("organizations", sa.Column("demo_created_ip", sa.String(64), nullable=True))
    if "demo_created_location" not in org_cols:
        op.add_column("organizations", sa.Column("demo_created_location", sa.String(255), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    org_cols = [c["name"] for c in inspector.get_columns("organizations")]
    if "demo_created_location" in org_cols:
        op.drop_column("organizations", "demo_created_location")
    if "demo_created_ip" in org_cols:
        op.drop_column("organizations", "demo_created_ip")
