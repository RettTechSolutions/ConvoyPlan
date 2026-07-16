"""store waypoint planned_arrival / planned_departure as naive wall-clock

Same fix as 0029 (which switched the convoy start_time / ablaufzeit columns),
now applied to the waypoint schedule columns. The planned arrival/departure
times are wall-clock times derived from the convoy start time; storing them in
`timestamptz` made asyncpg tag the naive value as UTC and return a
timezone-aware datetime on read. The frontend's `new Date(...)` then
re-interpreted that UTC instant in the browser's local timezone, shifting every
Zeitplan time by the local offset (e.g. Abmarsch 06:00 → 08:00 shown in CEST).

Switching the columns to `timestamp without time zone` makes the stored
wall-clock round-trip unchanged. `AT TIME ZONE 'UTC'` keeps the stored digits
as-is (they already are the intended wall-clock, because the schedule tags the
naive start time as UTC on write), rather than shifting them by the server
timezone.

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-16
"""
from alembic import op

revision = '0030'
down_revision = '0029'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE waypoints ALTER COLUMN planned_arrival TYPE timestamp without time zone "
        "USING planned_arrival AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE waypoints ALTER COLUMN planned_departure TYPE timestamp without time zone "
        "USING planned_departure AT TIME ZONE 'UTC'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE waypoints ALTER COLUMN planned_arrival TYPE timestamp with time zone "
        "USING planned_arrival AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE waypoints ALTER COLUMN planned_departure TYPE timestamp with time zone "
        "USING planned_departure AT TIME ZONE 'UTC'"
    )
