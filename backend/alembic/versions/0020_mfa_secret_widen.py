"""widen users.mfa_secret for encrypted ciphertext

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users", "mfa_secret",
        existing_type=sa.String(64),
        type_=sa.String(255),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "users", "mfa_secret",
        existing_type=sa.String(255),
        type_=sa.String(64),
        existing_nullable=True,
    )
