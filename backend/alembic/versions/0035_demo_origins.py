"""Add demo_origins — per-IP cooldown for demo sessions.

Eine Zeile je Client-IP, die eine Demo-Sitzung gestartet hat. Die Sperre muss
den Ablauf der Demo-Organisation überdauern (sonst wäre sie bei kurzer
Sitzungslaufzeit wirkungslos), deshalb eine eigene Tabelle statt einer Abfrage
auf `organizations.demo_created_ip`. Bereits laufende Demo-Sitzungen werden
übernommen, damit die Sperre unmittelbar nach dem Update greift.

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "demo_origins" in inspector.get_table_names():
        return

    op.create_table(
        "demo_origins",
        sa.Column("ip", sa.String(64), primary_key=True),
        sa.Column("first_created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("sessions", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_demo_origins_last_created_at", "demo_origins", ["last_created_at"])

    # Laufende Demo-Sitzungen als Startbestand übernehmen: je IP der jüngste
    # Start. Ohne das könnte jeder, der gerade eine Demo offen hat, direkt nach
    # dem Update noch eine zweite starten.
    org_cols = [c["name"] for c in inspector.get_columns("organizations")]
    if "demo_created_ip" in org_cols:
        op.execute(
            sa.text(
                """
                INSERT INTO demo_origins (ip, first_created_at, last_created_at, sessions)
                SELECT demo_created_ip, MIN(created_at), MAX(created_at), COUNT(*)
                FROM organizations
                WHERE is_demo IS TRUE AND demo_created_ip IS NOT NULL
                GROUP BY demo_created_ip
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "demo_origins" in inspector.get_table_names():
        op.drop_index("ix_demo_origins_last_created_at", table_name="demo_origins")
        op.drop_table("demo_origins")
