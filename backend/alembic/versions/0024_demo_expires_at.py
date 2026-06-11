"""Add demo_expires_at to organizations so demo sessions can be extended.

Existing demo orgs are backfilled with created_at + 24h (the previous implicit TTL).

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    org_cols = [c["name"] for c in inspector.get_columns("organizations")]
    if "demo_expires_at" not in org_cols:
        op.add_column(
            "organizations",
            sa.Column("demo_expires_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.execute(
            "UPDATE organizations SET demo_expires_at = created_at + interval '24 hours' "
            "WHERE is_demo = true AND demo_expires_at IS NULL"
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    org_cols = [c["name"] for c in inspector.get_columns("organizations")]
    if "demo_expires_at" in org_cols:
        op.drop_column("organizations", "demo_expires_at")
