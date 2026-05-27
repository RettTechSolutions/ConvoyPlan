"""add slug to organizations

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-27
"""
import re
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


# _slugify is intentionally duplicated here from app.models.organization.
# Alembic migrations must be self-contained and cannot import from app code
# because the app model layer may have evolved beyond what this migration expects.
def _slugify(text: str) -> str:
    text = text.lower()
    text = text.translate(str.maketrans("äöüß", "aous"))
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80].strip("-")


def upgrade() -> None:
    # 1. Spalte nullable hinzufügen
    op.add_column("organizations", sa.Column("slug", sa.String(80), nullable=True))

    # 2. Slugs aus Namen generieren (Python-Loop für Duplikat-Handling)
    conn = op.get_bind()
    orgs = conn.execute(sa.text("SELECT id, name FROM organizations ORDER BY created_at")).fetchall()
    seen: set[str] = set()
    for org in orgs:
        base = (_slugify(org.name) or "org")[:77]  # leave room for suffix "-99"
        slug = base
        i = 2
        while slug in seen:
            slug = f"{base}-{i}"
            i += 1
        seen.add(slug)
        conn.execute(
            sa.text("UPDATE organizations SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": str(org.id)},
        )

    # 3. NOT NULL + UNIQUE
    op.alter_column("organizations", "slug", nullable=False)
    op.create_unique_constraint("uq_organizations_slug", "organizations", ["slug"])
    op.create_index("idx_organizations_slug", "organizations", ["slug"])


def downgrade() -> None:
    op.drop_index("idx_organizations_slug", table_name="organizations")
    op.drop_constraint("uq_organizations_slug", "organizations", type_="unique")
    op.drop_column("organizations", "slug")
