"""Marschbefehl: Word-Vorlage je Organisation.

Keine Zeile heißt Beispielvorlage; ``services/marschbefehl_vorlage.py``.

Revision ID: 0073
Revises: 0072
Create Date: 2026-10-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marschbefehl_vorlagen",
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("dateiname", sa.String(200), nullable=False),
        sa.Column("groesse", sa.Integer(), nullable=False),
        sa.Column("daten", sa.LargeBinary(), nullable=False),
        sa.Column("hochgeladen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "hochgeladen_von_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("marschbefehl_vorlagen")
