"""Normalise user e-mail addresses to lower-case.

E-mail was stored and compared verbatim, so login was case-sensitive
(``Max@x.de`` couldn't log in as ``max@x.de``) and two accounts differing only
in case could coexist despite the unique-email constraint. Application code now
lower-cases every address on the way in; this migration lower-cases the existing
rows and adds a ``lower(email)`` unique index so case-insensitive uniqueness is
enforced by the database going forward.

If two rows would collide once lower-cased (a duplicate that already slipped
through), the migration aborts with the offending addresses instead of silently
merging or dropping an account — a human must resolve those first.

Revision ID: 0033
Revises: 0032
Create Date: 2026-07-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_users_email_lower"


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Refuse to proceed if lower-casing would violate uniqueness.
    dupes = bind.execute(
        sa.text(
            "SELECT lower(email) AS le, string_agg(email, ', ') AS addrs "
            "FROM users GROUP BY lower(email) HAVING count(*) > 1"
        )
    ).fetchall()
    if dupes:
        detail = "; ".join(f"{row.le} <- ({row.addrs})" for row in dupes)
        raise RuntimeError(
            "Cannot normalise user e-mails to lower-case: the following "
            "addresses collide case-insensitively. Merge or remove the duplicate "
            f"accounts, then re-run the migration -> {detail}"
        )

    # 2. Lower-case every stored address that isn't already normalised.
    bind.execute(sa.text("UPDATE users SET email = lower(email) WHERE email <> lower(email)"))

    # 3. Enforce case-insensitive uniqueness from now on.
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes("users")}
    if INDEX_NAME not in existing:
        op.create_index(INDEX_NAME, "users", [sa.text("lower(email)")], unique=True)


def downgrade() -> None:
    # The lower-casing of existing data is not reversible; only drop the index.
    bind = op.get_bind()
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes("users")}
    if INDEX_NAME in existing:
        op.drop_index(INDEX_NAME, table_name="users")
