"""rename update.channel 'beta' → 'nightly'

The update channel gained a third value: "beta" now means numbered
pre-releases (release candidates), while the old "beta" behaviour — tracking
every commit on main — is now called "nightly". Existing installs that chose
the old "beta" channel via the admin panel are stored in system_settings; move
them to "nightly" so their every-commit behaviour is preserved.

(Installs that select the channel purely via the UPDATE_CHANNEL env var are not
touched by this migration — see backend/app/config.py: those must set
UPDATE_CHANNEL=nightly manually.)

Revision ID: 0028
Revises: 0027
Create Date: 2026-07-09
"""
from alembic import op

revision = '0028'
down_revision = '0027'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE system_settings SET value = 'nightly' "
        "WHERE key = 'update.channel' AND value = 'beta'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE system_settings SET value = 'beta' "
        "WHERE key = 'update.channel' AND value = 'nightly'"
    )
