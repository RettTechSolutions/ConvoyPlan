"""system-scoped API keys

Erlaubt API-Keys ohne Organisationsbindung. Sie öffnen ausschließlich die
lesenden Endpunkte der Systemübersicht (/api/admin/system), damit ein
Monitoring-System sie ohne Superadmin-Login abfragen kann.

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("api_keys")}

    if "scope" not in columns:
        op.add_column(
            "api_keys",
            sa.Column("scope", sa.String(20), nullable=False, server_default="organization"),
        )

    # System keys belong to the instance, not to a tenant — so the FK has to
    # tolerate NULL. Existing rows are all organization-scoped and unaffected.
    op.alter_column("api_keys", "organization_id", existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    # Rows without an organization cannot survive the NOT NULL constraint.
    op.execute("DELETE FROM api_keys WHERE organization_id IS NULL")
    op.alter_column("api_keys", "organization_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("api_keys", "scope")
