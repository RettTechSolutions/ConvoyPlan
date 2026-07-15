"""store convoy start_time / ablaufzeit as naive wall-clock (timestamp without tz)

The convoy start time (and the Marschbefehl Ablaufzeit) are local wall-clock
times entered via timezone-naive `datetime-local` inputs in the frontend.
Storing them in `timestamptz` columns caused asyncpg to tag the naive value as
UTC and return a timezone-aware datetime on read. The frontend's `new Date(...)`
then re-interpreted that UTC instant in the browser's local timezone, shifting
the displayed time by the local offset (e.g. 06:30 saved → 08:30 shown in CEST).
Only freshly-read rows were affected; the create response returned the still-naive
in-memory value, which is why the shift appeared on edit/reload but not right
after creating.

Switching the columns to `timestamp without time zone` makes the entered
wall-clock round-trip unchanged. The `AT TIME ZONE 'UTC'` conversion keeps the
stored digits as-is (the value the user originally typed on the create path),
rather than shifting them by the server timezone.

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-15
"""
from alembic import op

revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE convoys ALTER COLUMN start_time TYPE timestamp without time zone "
        "USING start_time AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE convoys ALTER COLUMN ablaufzeit TYPE timestamp without time zone "
        "USING ablaufzeit AT TIME ZONE 'UTC'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE convoys ALTER COLUMN start_time TYPE timestamp with time zone "
        "USING start_time AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE convoys ALTER COLUMN ablaufzeit TYPE timestamp with time zone "
        "USING ablaufzeit AT TIME ZONE 'UTC'"
    )
