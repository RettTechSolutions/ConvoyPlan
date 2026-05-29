"""convoy share links

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "convoy_share_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("convoy_id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(16), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("scope", sa.String(20), nullable=False, server_default="track"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["convoy_id"], ["convoys.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_convoy_share_links_slug"),
    )
    op.create_index("ix_convoy_share_links_convoy_id", "convoy_share_links", ["convoy_id"])
    op.create_index("ix_convoy_share_links_slug", "convoy_share_links", ["slug"])


def downgrade() -> None:
    op.drop_index("ix_convoy_share_links_slug", table_name="convoy_share_links")
    op.drop_index("ix_convoy_share_links_convoy_id", table_name="convoy_share_links")
    op.drop_table("convoy_share_links")
