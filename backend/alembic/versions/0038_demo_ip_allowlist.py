"""Add demo_ip_allowlist — dauerhafte Ausnahmen von der Demo-IP-Sperre.

Gegenstück zu `demo_origins` (0035): Adressen und Netze, für die die
Karenzzeit nicht gilt — Firmenanschluss, Messe-WLAN, eigener Vertrieb. Ohne
diese Liste musste dort nach jeder Vorführung von Hand entsperrt werden.

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "demo_ip_allowlist" in inspector.get_table_names():
        return

    op.create_table(
        "demo_ip_allowlist",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("pattern", sa.String(64), nullable=False),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255), nullable=True),
    )
    # Eindeutig, damit derselbe Anschluss nicht mehrfach in der Liste landet.
    op.create_index("ix_demo_ip_allowlist_pattern", "demo_ip_allowlist", ["pattern"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    if "demo_ip_allowlist" in sa.inspect(bind).get_table_names():
        op.drop_index("ix_demo_ip_allowlist_pattern", table_name="demo_ip_allowlist")
        op.drop_table("demo_ip_allowlist")
