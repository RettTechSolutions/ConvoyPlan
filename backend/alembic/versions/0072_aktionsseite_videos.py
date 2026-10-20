"""Aktionsseite: Videos von unterwegs.

Ein Video aus der Telegram-Gruppe wird im Medien-Container neu kodiert und als
Datei unter ``/uploads/aktionsseite/videos/`` abgelegt; hier steht nur, was
dazu gehört. Das Standbild ist ein gewöhnliches Bild des Beitrags
(``public_tracker_photos``). Plan:
docs/superpowers/plans/2026-10-13-fotos-auf-der-aktionsseite.md, § 15.

Revision ID: 0072
Revises: 0071
Create Date: 2026-10-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "public_tracker_videos",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "post_id", sa.UUID(),
            sa.ForeignKey("public_tracker_posts.id", ondelete="CASCADE"),
            nullable=False, unique=True,
        ),
        sa.Column("public_id", sa.String(32), nullable=False, unique=True),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("seconds", sa.Float(), nullable=False),
        sa.Column("sound", sa.Boolean(), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("public_tracker_videos")
