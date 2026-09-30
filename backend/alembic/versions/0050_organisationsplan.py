"""Plan je Organisation (Hosting-Pakete, Einsatz-Paket).

Eine Zeile je Organisation, für die der Betreiber ein Paket gesetzt hat —
keine Zeile heißt ohne Plan und ohne Grenzen. Bestehende Organisationen
bekommen deshalb **keine** Zeile: ein Update macht aus keiner Installation
eine mit erreichter Grenze. Wer auf seiner Hosting-Instanz Pakete führt,
setzt sie im Adminportal.

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_plans",
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("plan", sa.String(30), nullable=False),
        sa.Column("max_vehicles", sa.Integer(), nullable=True),
        sa.Column("max_planners", sa.Integer(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_by_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("organization_plans")
