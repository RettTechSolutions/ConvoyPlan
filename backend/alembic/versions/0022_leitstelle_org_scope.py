"""org-scoping & proposal workflow for leitstellen

Adds org_id, status, proposed_by_org_id, review_note and district_codes to
leitstellen. Existing rows are treated as global (superadmin-managed).

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c["name"] for c in inspector.get_columns("leitstellen")]

    if "district_codes" not in cols:
        op.add_column("leitstellen", sa.Column("district_codes", sa.JSON(), nullable=True))
    if "status" not in cols:
        op.add_column(
            "leitstellen",
            sa.Column("status", sa.String(length=20), nullable=False, server_default="global"),
        )
    if "review_note" not in cols:
        op.add_column("leitstellen", sa.Column("review_note", sa.String(length=500), nullable=True))
    if "org_id" not in cols:
        op.add_column("leitstellen", sa.Column("org_id", sa.UUID(), nullable=True))
        op.create_foreign_key(
            "fk_leitstellen_org_id",
            "leitstellen", "organizations",
            ["org_id"], ["id"],
            ondelete="CASCADE",
        )
    if "proposed_by_org_id" not in cols:
        op.add_column("leitstellen", sa.Column("proposed_by_org_id", sa.UUID(), nullable=True))
        op.create_foreign_key(
            "fk_leitstellen_proposed_by_org_id",
            "leitstellen", "organizations",
            ["proposed_by_org_id"], ["id"],
            ondelete="SET NULL",
        )

    existing_indexes = [idx["name"] for idx in inspector.get_indexes("leitstellen")]
    if "ix_leitstellen_org_id" not in existing_indexes:
        op.create_index("ix_leitstellen_org_id", "leitstellen", ["org_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_indexes = [idx["name"] for idx in inspector.get_indexes("leitstellen")]
    if "ix_leitstellen_org_id" in existing_indexes:
        op.drop_index("ix_leitstellen_org_id", table_name="leitstellen")

    cols = [c["name"] for c in inspector.get_columns("leitstellen")]
    if "proposed_by_org_id" in cols:
        op.drop_constraint("fk_leitstellen_proposed_by_org_id", "leitstellen", type_="foreignkey")
        op.drop_column("leitstellen", "proposed_by_org_id")
    if "org_id" in cols:
        op.drop_constraint("fk_leitstellen_org_id", "leitstellen", type_="foreignkey")
        op.drop_column("leitstellen", "org_id")
    for col in ("review_note", "status", "district_codes"):
        if col in cols:
            op.drop_column("leitstellen", col)
