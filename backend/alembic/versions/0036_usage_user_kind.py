"""Separate portal usage by user kind (member / demo / admin).

Die Portalnutzung zählte bisher jeden Token gleich: eine Demo-Sitzung erzeugt
aber je Aufruf ein neues Wegwerfkonto, und der Superadmin im Admin-Portal ist
der Betreiber selbst — beides gehört nicht in die Kennzahl „wie viele Nutzer
arbeiten im Portal". Diese Revision ergänzt

* ``user_activity_days.kind`` (Teil des Tagesschlüssels — derselbe Superadmin
  kann an einem Tag im Admin-Portal *und* in einer Organisation arbeiten),
* ``system_metrics.active_demo_users`` / ``active_admin_users``,
* die passenden Tagesaggregate in ``system_metrics_daily``.

Der Bestand wird bestmöglich nachgetragen: Demo erkennt man am Konto oder an
der Organisation, Administratoren an ``is_superadmin`` ohne Organisation.

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

_OLD_UNIQUE = "uq_user_activity_user_day"
_NEW_UNIQUE = "uq_user_activity_user_day_kind"


def _columns(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # ── Stichproben: Demo- und Admin-Nutzer getrennt zählen ──────────────────
    if "system_metrics" in tables:
        cols = _columns(inspector, "system_metrics")
        for name in ("active_demo_users", "active_admin_users"):
            if name not in cols:
                op.add_column(
                    "system_metrics",
                    sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
                )

    if "system_metrics_daily" in tables:
        cols = _columns(inspector, "system_metrics_daily")
        for name in ("active_demo_users_avg", "active_admin_users_avg"):
            if name not in cols:
                op.add_column("system_metrics_daily", sa.Column(name, sa.Float(), nullable=True))
        for name in ("unique_demo_users", "unique_admin_users"):
            if name not in cols:
                op.add_column("system_metrics_daily", sa.Column(name, sa.Integer(), nullable=True))

    # ── Tagesaktivität: Nutzergruppe als Teil des Schlüssels ─────────────────
    if "user_activity_days" not in tables:
        return

    if "kind" not in _columns(inspector, "user_activity_days"):
        op.add_column(
            "user_activity_days",
            sa.Column("kind", sa.String(16), nullable=False, server_default="member"),
        )
        op.create_index("ix_user_activity_days_kind", "user_activity_days", ["kind"])

        # Bestand nachtragen. Demo-Konten werden nach Ablauf gelöscht; erhalten
        # bleiben dann Zeilen ohne zugehörigen Benutzer *und* ohne Organisation
        # — bei einem Portal, in dem reguläre Konten dauerhaft bestehen, ist das
        # praktisch immer eine abgelaufene Demo-Sitzung.
        op.execute(
            sa.text(
                """
                UPDATE user_activity_days SET kind = 'demo'
                WHERE user_id IN (SELECT id FROM users WHERE is_demo IS TRUE)
                   OR org_id IN (SELECT id FROM organizations WHERE is_demo IS TRUE)
                   OR (
                        org_id IS NULL
                        AND user_id NOT IN (SELECT id FROM users)
                   )
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE user_activity_days SET kind = 'admin'
                WHERE kind = 'member'
                  AND org_id IS NULL
                  AND user_id IN (SELECT id FROM users WHERE is_superadmin IS TRUE)
                """
            )
        )

    constraints = {c["name"] for c in inspector.get_unique_constraints("user_activity_days")}
    if _OLD_UNIQUE in constraints:
        op.drop_constraint(_OLD_UNIQUE, "user_activity_days", type_="unique")
    if _NEW_UNIQUE not in constraints:
        op.create_unique_constraint(
            _NEW_UNIQUE, "user_activity_days", ["user_id", "day", "kind"]
        )

    # Die Tagesaggregate zählten bisher alle Gruppen zusammen. Sie werden aus
    # user_activity_days neu berechnet, damit Bericht und Chart übereinstimmen.
    if "system_metrics_daily" in tables:
        op.execute(
            sa.text(
                """
                UPDATE system_metrics_daily d SET
                    unique_users = COALESCE((
                        SELECT COUNT(DISTINCT a.user_id) FROM user_activity_days a
                        WHERE a.day = d.day AND a.kind = 'member'), 0),
                    unique_demo_users = COALESCE((
                        SELECT COUNT(DISTINCT a.user_id) FROM user_activity_days a
                        WHERE a.day = d.day AND a.kind = 'demo'), 0),
                    unique_admin_users = COALESCE((
                        SELECT COUNT(DISTINCT a.user_id) FROM user_activity_days a
                        WHERE a.day = d.day AND a.kind = 'admin'), 0)
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "user_activity_days" in tables:
        constraints = {c["name"] for c in inspector.get_unique_constraints("user_activity_days")}
        if _NEW_UNIQUE in constraints:
            op.drop_constraint(_NEW_UNIQUE, "user_activity_days", type_="unique")
        if "kind" in _columns(inspector, "user_activity_days"):
            # Ohne die Gruppe kann es je Benutzer und Tag nur eine Zeile geben —
            # Mehrfachzeilen vorher zusammenführen, sonst scheitert der Index.
            op.execute(
                sa.text(
                    """
                    DELETE FROM user_activity_days a
                    WHERE EXISTS (
                        SELECT 1 FROM user_activity_days b
                        WHERE b.user_id = a.user_id AND b.day = a.day AND b.id < a.id
                    )
                    """
                )
            )
            op.drop_index("ix_user_activity_days_kind", table_name="user_activity_days")
            op.drop_column("user_activity_days", "kind")
        if _OLD_UNIQUE not in constraints:
            op.create_unique_constraint(_OLD_UNIQUE, "user_activity_days", ["user_id", "day"])

    if "system_metrics_daily" in tables:
        cols = _columns(inspector, "system_metrics_daily")
        for name in (
            "active_demo_users_avg",
            "active_admin_users_avg",
            "unique_demo_users",
            "unique_admin_users",
        ):
            if name in cols:
                op.drop_column("system_metrics_daily", name)

    if "system_metrics" in tables:
        cols = _columns(inspector, "system_metrics")
        for name in ("active_demo_users", "active_admin_users"):
            if name in cols:
                op.drop_column("system_metrics", name)
