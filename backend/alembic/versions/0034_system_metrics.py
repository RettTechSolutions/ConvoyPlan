"""system metrics time series (Admin → Systemübersicht)

Legt die drei Zeitreihentabellen an: Rohstichproben, Tagesaggregate und die
Tagesaktivität je Benutzer.

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "system_metrics" not in existing:
        op.create_table(
            "system_metrics",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("interval_s", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cpu_percent", sa.Float(), nullable=True),
            sa.Column("cpu_count", sa.Integer(), nullable=True),
            sa.Column("load1", sa.Float(), nullable=True),
            sa.Column("load5", sa.Float(), nullable=True),
            sa.Column("load15", sa.Float(), nullable=True),
            sa.Column("mem_total_bytes", sa.BigInteger(), nullable=True),
            sa.Column("mem_used_bytes", sa.BigInteger(), nullable=True),
            sa.Column("mem_available_bytes", sa.BigInteger(), nullable=True),
            sa.Column("mem_percent", sa.Float(), nullable=True),
            sa.Column("swap_total_bytes", sa.BigInteger(), nullable=True),
            sa.Column("swap_used_bytes", sa.BigInteger(), nullable=True),
            sa.Column("disk_total_bytes", sa.BigInteger(), nullable=True),
            sa.Column("disk_used_bytes", sa.BigInteger(), nullable=True),
            sa.Column("disk_percent", sa.Float(), nullable=True),
            sa.Column("disk_read_bytes_s", sa.Float(), nullable=True),
            sa.Column("disk_write_bytes_s", sa.Float(), nullable=True),
            sa.Column("disk_util_percent", sa.Float(), nullable=True),
            sa.Column("psi_cpu_avg10", sa.Float(), nullable=True),
            sa.Column("psi_mem_avg10", sa.Float(), nullable=True),
            sa.Column("psi_io_avg10", sa.Float(), nullable=True),
            sa.Column("psi_io_avg60", sa.Float(), nullable=True),
            sa.Column("db_size_bytes", sa.BigInteger(), nullable=True),
            sa.Column("db_connections", sa.Integer(), nullable=True),
            sa.Column("containers_total", sa.Integer(), nullable=True),
            sa.Column("containers_running", sa.Integer(), nullable=True),
            sa.Column("containers_unhealthy", sa.Integer(), nullable=True),
            sa.Column("active_users", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("active_orgs", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("logins", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("request_errors", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("avg_response_ms", sa.Float(), nullable=True),
            sa.Column("active_convoys", sa.Integer(), nullable=True),
            sa.Column("disks", sa.JSON(), nullable=True),
            sa.Column("containers", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_system_metrics_captured_at", "system_metrics", ["captured_at"])

    if "system_metrics_daily" not in existing:
        op.create_table(
            "system_metrics_daily",
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("samples", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cpu_avg", sa.Float(), nullable=True),
            sa.Column("cpu_max", sa.Float(), nullable=True),
            sa.Column("load_avg", sa.Float(), nullable=True),
            sa.Column("load_max", sa.Float(), nullable=True),
            sa.Column("mem_percent_avg", sa.Float(), nullable=True),
            sa.Column("mem_percent_max", sa.Float(), nullable=True),
            sa.Column("mem_used_max_bytes", sa.BigInteger(), nullable=True),
            sa.Column("disk_percent_avg", sa.Float(), nullable=True),
            sa.Column("disk_percent_max", sa.Float(), nullable=True),
            sa.Column("disk_used_max_bytes", sa.BigInteger(), nullable=True),
            sa.Column("disk_read_bytes_s_avg", sa.Float(), nullable=True),
            sa.Column("disk_write_bytes_s_avg", sa.Float(), nullable=True),
            sa.Column("psi_io_avg", sa.Float(), nullable=True),
            sa.Column("psi_io_max", sa.Float(), nullable=True),
            sa.Column("psi_cpu_avg", sa.Float(), nullable=True),
            sa.Column("psi_mem_avg", sa.Float(), nullable=True),
            sa.Column("db_size_max_bytes", sa.BigInteger(), nullable=True),
            sa.Column("containers_unhealthy_max", sa.Integer(), nullable=True),
            sa.Column("containers_running_min", sa.Integer(), nullable=True),
            sa.Column("active_users_avg", sa.Float(), nullable=True),
            sa.Column("active_users_max", sa.Integer(), nullable=True),
            sa.Column("unique_users", sa.Integer(), nullable=True),
            sa.Column("logins", sa.Integer(), nullable=True),
            sa.Column("requests", sa.Integer(), nullable=True),
            sa.Column("request_errors", sa.Integer(), nullable=True),
            sa.Column("avg_response_ms", sa.Float(), nullable=True),
            sa.PrimaryKeyConstraint("day"),
        )

    if "user_activity_days" not in existing:
        op.create_table(
            "user_activity_days",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("org_id", sa.UUID(), nullable=True),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "day", name="uq_user_activity_user_day"),
        )
        op.create_index("ix_user_activity_days_user_id", "user_activity_days", ["user_id"])
        op.create_index("ix_user_activity_days_org_id", "user_activity_days", ["org_id"])
        op.create_index("ix_user_activity_days_day", "user_activity_days", ["day"])


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "user_activity_days" in existing:
        op.drop_index("ix_user_activity_days_day", table_name="user_activity_days")
        op.drop_index("ix_user_activity_days_org_id", table_name="user_activity_days")
        op.drop_index("ix_user_activity_days_user_id", table_name="user_activity_days")
        op.drop_table("user_activity_days")
    if "system_metrics_daily" in existing:
        op.drop_table("system_metrics_daily")
    if "system_metrics" in existing:
        op.drop_index("ix_system_metrics_captured_at", table_name="system_metrics")
        op.drop_table("system_metrics")
