"""Add demo_leads — Kontaktdaten zu einer Demo-Sitzung.

Wer die Demo startet, gibt seine E-Mail-Adresse an (Name optional). Die Zeile
liegt außerhalb der Demo-Org, weil der Retention-Job die Org beim Ablauf
löscht — die Nachfrage-Mail geht aber genau danach raus.

Revision ID: 0040
Revises: 0039
Create Date: 2026-09-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "demo_leads" in inspector.get_table_names():
        return

    op.create_table(
        "demo_leads",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        # SET NULL: Die Kontaktangabe überlebt das Aufräumen der Demo-Org.
        sa.Column(
            "org_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("org_slug", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("session_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("followup_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("followup_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("followup_error", sa.String(255), nullable=True),
        sa.Column("unsubscribe_token", sa.String(64), nullable=False),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_demo_leads_email", "demo_leads", ["email"])
    # Der Versandjob sucht über den Ablaufzeitpunkt.
    op.create_index("ix_demo_leads_session_expires_at", "demo_leads", ["session_expires_at"])
    # Eindeutig: das Token ist der Schlüssel des Abmeldelinks.
    op.create_index("ix_demo_leads_unsubscribe_token", "demo_leads", ["unsubscribe_token"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    if "demo_leads" in sa.inspect(bind).get_table_names():
        op.drop_index("ix_demo_leads_unsubscribe_token", table_name="demo_leads")
        op.drop_index("ix_demo_leads_session_expires_at", table_name="demo_leads")
        op.drop_index("ix_demo_leads_email", table_name="demo_leads")
        op.drop_table("demo_leads")
