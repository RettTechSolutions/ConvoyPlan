"""Gebietsschlüssel der Leitstellen um ein Länderpräfix ergänzen.

Bis hierher war ein Gebietsschlüssel der nackte fünfstellige AGS eines
deutschen Landkreises ("08115"). Mit der Ausweitung auf DACH kommen
österreichische Bezirkskennziffern (dreistellig) und Schweizer Kantone dazu —
ohne Präfix kollidieren die Nummernkreise. Alle Schlüssel tragen jetzt das
ISO-Länderkürzel: "DE-08115", "AT-322", "CH-040", "LI-000".

Bestehende Zeilen sind ausnahmslos deutsch (etwas anderes war nicht wählbar)
und bekommen deshalb "DE-" vorangestellt.

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-27
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

_SELECT = sa.text(
    "SELECT id, district_codes FROM leitstellen WHERE district_codes IS NOT NULL"
)
_UPDATE = sa.text(
    "UPDATE leitstellen SET district_codes = CAST(:codes AS json) WHERE id = :id"
)


def _rewrite(transform) -> None:
    """Jede Schlüsselliste durch *transform* schicken und nur Geänderte schreiben."""
    bind = op.get_bind()
    for row_id, codes in bind.execute(_SELECT).fetchall():
        # Je nach Treiber kommt die JSON-Spalte als Liste oder als Text zurück.
        if isinstance(codes, str):
            try:
                codes = json.loads(codes)
            except ValueError:
                continue
        if not isinstance(codes, list):
            continue
        updated = transform([c for c in codes if isinstance(c, str)])
        if updated != codes:
            bind.execute(_UPDATE, {"codes": json.dumps(updated), "id": row_id})


PREFIXES = ("DE-", "AT-", "CH-", "LI-")


def add_prefix(codes: list[str]) -> list[str]:
    """Nackte AGS um "DE-" ergänzen.

    Idempotent: bereits präfixierte Schlüssel bleiben unangetastet, damit ein
    erneuter Lauf (oder ein Downgrade/Upgrade-Zyklus) nichts doppelt setzt.
    """
    return [c if c[:3] in PREFIXES else f"DE-{c}" for c in codes]


def strip_prefix(codes: list[str]) -> list[str]:
    """Auf das alte, rein deutsche Schema zurückfallen.

    AT/CH/LI-Gebiete fallen dabei weg — das alte Schema kennt sie nicht, und als
    nackte Nummer blieben sie als nicht auflösbare Geisterschlüssel stehen.
    """
    return [c[3:] for c in codes if c.startswith("DE-")]


def upgrade() -> None:
    _rewrite(add_prefix)


def downgrade() -> None:
    _rewrite(strip_prefix)
