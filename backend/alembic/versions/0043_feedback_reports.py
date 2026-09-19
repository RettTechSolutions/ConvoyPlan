"""Meldungen aus der Anwendung — Fehler und Wünsche.

Eine Tabelle, keine Fremdschlüssel mit ``CASCADE``: eine gelöschte
Organisation oder ein gelöschter Benutzer nimmt die Meldung nicht mit. Was
dann fehlt, sind die Verweise; die Textkopien von Name, Kürzel und Adresse
stehen daneben und bleiben lesbar.

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "feedback_reports" in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        "feedback_reports",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(20), nullable=False, server_default="neu"),
        sa.Column(
            "org_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("org_slug", sa.String(80), nullable=True),
        sa.Column("org_name", sa.String(200), nullable=True),
        sa.Column(
            "user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("reporter_email", sa.String(255), nullable=True),
        sa.Column("reporter_name", sa.String(200), nullable=True),
        sa.Column("reporter_role", sa.String(20), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("page_url", sa.String(500), nullable=True),
        sa.Column("user_agent", sa.String(400), nullable=True),
        sa.Column("app_version", sa.String(80), nullable=True),
        sa.Column("viewport", sa.String(32), nullable=True),
        sa.Column("screenshot_name", sa.String(80), nullable=True),
        sa.Column("screenshot_bytes", sa.Integer(), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column(
            "handled_by_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    # Die drei Spalten, über die das Adminportal filtert und sortiert. Ohne sie
    # ist die Liste bei wenigen hundert Zeilen unauffällig und bei zehntausend
    # ein Vollscan je Reiterwechsel.
    op.create_index("ix_feedback_reports_kind", "feedback_reports", ["kind"])
    op.create_index("ix_feedback_reports_status", "feedback_reports", ["status"])
    op.create_index("ix_feedback_reports_created_at", "feedback_reports", ["created_at"])


def downgrade() -> None:
    op.drop_table("feedback_reports")
