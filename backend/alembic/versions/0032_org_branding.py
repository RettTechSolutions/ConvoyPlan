"""Add per-organization branding overrides.

Org admins customize branding only for their own organization; the
platform-wide branding (SystemSetting `branding.*`) stays superadmin-only.

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    org_cols = [c["name"] for c in inspector.get_columns("organizations")]
    if "branding" not in org_cols:
        # JSON dict of branding overrides (app_name, colors, logo filenames);
        # NULL = no override, the org inherits the platform branding.
        op.add_column("organizations", sa.Column("branding", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    org_cols = [c["name"] for c in inspector.get_columns("organizations")]
    if "branding" in org_cols:
        op.drop_column("organizations", "branding")
