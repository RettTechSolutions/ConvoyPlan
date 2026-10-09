"""Tracker im Paket einer Organisation (services/org_plan.py).

``organization_plans.max_trackers``: wie viele Ortungsgeräte das Paket enthält.
NULL heißt unbegrenzt — auch für jeden schon gesetzten Plan, damit keine
Organisation durch das Update eine Überschreitung gemeldet bekommt. Die Grenze
ist weich wie die übrigen: gemeldet, nicht verhindert.

Revision ID: 0061
Revises: 0060
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organization_plans", sa.Column("max_trackers", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("organization_plans", "max_trackers")
