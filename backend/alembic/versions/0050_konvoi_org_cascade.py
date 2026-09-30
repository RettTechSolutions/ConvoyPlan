"""Konvois gehen mit ihrer Organisation.

``convoys.organization_id`` zeigte seit 0002 mit ``ON DELETE SET NULL`` auf die
Organisation. Wer eine Organisation löschte — Superadmin wie Inhaber —, ließ
ihre Konvois samt Wegpunkten, Route, Positionen und Tracking-Links ohne
Zuordnung zurück. Erreichbar waren sie danach für niemanden mehr, denn jeder
Zugriff prüft ``convoy.organization_id == org.id``; gelöscht aber auch nicht.
Für eine Löschzusage nach Art. 17 DSGVO ist das zu wenig.

Die Regel wandert deshalb an den Fremdschlüssel: ``ON DELETE CASCADE``. Von dort
reicht sie über die schon bestehenden Kaskaden (0001, 0002, 0017) bis zu
Wegpunkten, Route, Positionen, Fahrzeugzuordnungen und Tracking-Links — egal,
auf welchem Weg die Organisation verschwindet.

Die Migration löscht außerdem die Konvois, die bereits verwaist sind. Jeder
Konvoi wird mit Organisation angelegt (``api/routes/convoys.py``); ein Konvoi
ohne ist also ein Rest einer gelöschten Organisation oder stammt aus der Zeit
vor 0002 — in beiden Fällen für keinen Nutzer mehr erreichbar.

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-30
"""
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM convoys WHERE organization_id IS NULL")
    op.drop_constraint("fk_convoy_organization", "convoys", type_="foreignkey")
    op.create_foreign_key(
        "fk_convoy_organization", "convoys", "organizations",
        ["organization_id"], ["id"], ondelete="CASCADE",
    )


def downgrade() -> None:
    # Die gelöschten Waisen kommen nicht zurück — sie waren ohnehin unerreichbar.
    op.drop_constraint("fk_convoy_organization", "convoys", type_="foreignkey")
    op.create_foreign_key(
        "fk_convoy_organization", "convoys", "organizations",
        ["organization_id"], ["id"], ondelete="SET NULL",
    )
