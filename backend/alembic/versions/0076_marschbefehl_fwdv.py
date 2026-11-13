"""Marschbefehl nach FwDV 100, Anlage 4.

Das Muster der Dienstvorschrift kennt im Kopf Abgangsort, den Raum und die
Karte, unter jeder Hauptziffer feste Unterpunkte und am Schluss Verteiler und
Unterschrift (Name, Dienststellung). Bis hierher gab es dafür nur Freitexte je
Hauptziffer. Die bestehenden Spalten behalten ihre Bedeutung und werden dem
FwDV-Punkt zugeordnet, der ihnen entspricht: ``lage`` ist die Gefahren- /
Schadenlage, ``auftrag`` der erhaltene Auftrag, ``versorgung`` steht unter 4.
als Ergänzung zu den vier Unterpunkten. Nichts wird verschoben oder geteilt —
ein Freitext lässt sich nicht verlässlich auf Unterpunkte aufteilen.

Alles nullable ohne Vorgabe: leer heißt „nichts angeordnet", und die FwDV sagt
selbst, dass nicht zu jedem Punkt etwas angeordnet werden muss.

Revision ID: 0076
Revises: 0075
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None

# (Spalte, Typ) in der Reihenfolge der FwDV.
SPALTEN = (
    ("abgangsort", sa.String(200)),
    ("marschraum", sa.String(200)),
    ("karte", sa.String(200)),
    ("lage_eigene", sa.Text()),
    ("kraefte", sa.Text()),
    ("marschfuehrer", sa.String(100)),
    ("einzelgruppen_fuehrer", sa.Text()),
    ("marschabstand", sa.String(100)),
    ("beleuchtung", sa.Text()),
    ("marschueberwachung", sa.Text()),
    ("besonderes", sa.Text()),
    ("verpflegung", sa.Text()),
    ("betriebsstoff", sa.Text()),
    ("instandsetzung", sa.Text()),
    ("aerztliche_versorgung", sa.Text()),
    ("verbindungen", sa.Text()),
    ("platz_fuehrung", sa.String(200)),
    ("verteiler", sa.Text()),
    ("unterschrift_name", sa.String(100)),
    ("unterschrift_dienststellung", sa.String(100)),
)


def upgrade() -> None:
    for name, typ in SPALTEN:
        op.add_column("convoys", sa.Column(name, typ, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(SPALTEN):
        op.drop_column("convoys", name)
