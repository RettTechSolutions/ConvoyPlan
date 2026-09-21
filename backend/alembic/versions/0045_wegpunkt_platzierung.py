"""Ein vorgeschlagener Halt sagt selbst, dass er noch keinen Platz hat.

``pending_placement`` markiert einen Wegpunkt, den die Anwendung **vorgeschlagen**
hat (Technischer Halt, Lenkpause, Tankstopp) und den noch niemand in die
Reihenfolge einsortiert hat. Die nächste Routenberechnung ordnet genau diese
Wegpunkte entlang der vorherigen Route ein und löscht die Marke.

Bisher wurde dafür geraten: „der zusammenhängende Lauf von ``technical_stop``
am Listenende". Das traf den Normalfall, weil die Oberfläche einen Vorschlag
hinten anhängt — aber eben auch einen Technischen Halt, den jemand bewusst als
**letzten** Wegpunkt gesetzt hatte. Der wurde dann einmal verschoben. Mit der
Marke entscheidet die Herkunft statt der Position.

Der Bestand bekommt genau die bisherige Regel mit: der Lauf am Ende jeder
Wegpunktliste wird einmal als unplatziert markiert. Nach der nächsten Berechnung
ist die Marke weg und die neue Regel gilt genau. Ein Verzicht auf den Backfill
wäre die schlechtere Wahl: ein vor dem Update angehängter Tankstopp bliebe für
immer am Listenende stehen — und genau daraus entstand der Umweg von mehreren
hundert Kilometern.

Die Auswahl steht als ``unplatzierte()`` daneben und nicht in einer
``UPDATE … WHERE``-Bedingung: sie schreibt gespeicherte Nutzdaten um, und was
Nutzdaten umschreibt, wird hier ohne Datenbank geprüft
(``tests/test_wegpunkt_platzierung_migration.py``, wie bei 0039).

Revision ID: 0045
Revises: 0044
Create Date: 2026-09-21
"""
from collections import defaultdict
from typing import Any, Iterable

import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

TECHNICAL_STOP = "technical_stop"


def unplatzierte(zeilen: Iterable[tuple[Any, Any, str, int]]) -> list[Any]:
    """IDs der Wegpunkte, die als noch nicht einsortiert gelten.

    *zeilen* ist ``(id, convoy_id, type, order_index)``. Genommen wird je Konvoi
    der zusammenhängende Lauf von Technischen Halten am Ende der nach
    ``order_index`` sortierten Liste — die Regel, die bis zu dieser Migration
    galt. Steht hinter einem Halt noch ein gewöhnlicher Wegpunkt, hat ihn jemand
    dorthin gesetzt, und er bleibt unangetastet.
    """
    je_konvoi: dict[Any, list[tuple[int, Any, str]]] = defaultdict(list)
    for wp_id, convoy_id, typ, order_index in zeilen:
        je_konvoi[convoy_id].append((order_index or 0, wp_id, typ))

    treffer: list[Any] = []
    for eintraege in je_konvoi.values():
        eintraege.sort(key=lambda e: e[0])
        for _, wp_id, typ in reversed(eintraege):
            if typ != TECHNICAL_STOP:
                break
            treffer.append(wp_id)
    return treffer


def upgrade() -> None:
    op.add_column(
        "waypoints",
        sa.Column(
            "pending_placement",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    bind = op.get_bind()
    zeilen = bind.execute(
        sa.text("SELECT id, convoy_id, type, order_index FROM waypoints")
    ).fetchall()
    treffer = unplatzierte(tuple(zeile) for zeile in zeilen)
    if treffer:
        bind.execute(
            sa.text(
                "UPDATE waypoints SET pending_placement = true WHERE id IN :ids"
            ).bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": treffer},
        )


def downgrade() -> None:
    op.drop_column("waypoints", "pending_placement")
