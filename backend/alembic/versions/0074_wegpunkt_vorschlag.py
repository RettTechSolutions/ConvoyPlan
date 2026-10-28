"""Ein übernommener Halt-Vorschlag weiß, dass er einer ist.

``vorschlag_art`` (tech | break | daily_rest) steht an einem Wegpunkt, der aus der
Halte-Empfehlung übernommen und seitdem nicht angefasst wurde. Ändert sich die
Route, prüft die Analyse diese Halte gegen eine frische Empfehlung und bietet an,
sie neu zu verteilen — siehe ``app/services/halte_vorschlag.py``. NULL heißt:
selbst gesetzt oder geändert, gehört dem Menschen.

Der Bestand bekommt die Marke, wo die Herkunft am Wegpunkt noch abzulesen ist:
bis zu dieser Migration hieß jeder übernommene Vorschlag „Technischer Halt
(km 126.1)", „Lenkpause (km …)" oder „Tagesruhezeit (km …)", und das Formular
erlaubt, den Namen zu ändern. Steht der Name noch so da und passen Art, Grund und
Dauer zur Empfehlung, gilt der Halt als unberührt. Ohne Backfill bliebe genau der
gemeldete Fall — doppelte Tagesruhe nach einer Umplanung — für alle bestehenden
Planungen ungelöst.

Die Auswahl steht als ``vorschlaege()`` daneben und nicht in einer
``UPDATE … WHERE``-Bedingung: sie entscheidet über Bestandsdaten und wird ohne
Datenbank geprüft (``tests/test_wegpunkt_vorschlag_migration.py``, wie bei 0046).

Revision ID: 0074
Revises: 0073
Create Date: 2026-10-28
"""
import re
from typing import Any, Iterable

import sqlalchemy as sa
from alembic import op

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None

_NAME = re.compile(r"^(Technischer Halt|Lenkpause|Tagesruhezeit) \(km \d+(?:\.\d+)?\)$")
_ART = {"Technischer Halt": "tech", "Lenkpause": "break", "Tagesruhezeit": "daily_rest"}
# Wie fuel.BREAK_DURATION_MIN / DAILY_REST_MIN — hier festgeschrieben, damit eine
# spätere Änderung dort die Migration nicht umdeutet.
_LENKPAUSE_MIN = 45
_TAGESRUHE_MIN = 660


def vorschlaege(zeilen: Iterable[tuple[Any, str, str, str | None, int | None]]) -> list[tuple[Any, str]]:
    """``(id, art)`` der Wegpunkte, die als unberührt übernommene Vorschläge gelten.

    *zeilen* ist ``(id, name, type, halt_purpose, hold_duration_min)``. Die
    Oberfläche legte TH ohne Grund an, Lenkpause und Tagesruhe mit ``rest``; die
    Dauer der Lenkpause ist mindestens 45 min (bei großen Verbänden die längere
    TH-Dauer), die der Tagesruhe genau 11 h. Die TH-Dauer hängt an der Zahl der
    Fahrzeuge zur Zeit der Übernahme und lässt sich nicht nachprüfen.
    """
    treffer: list[tuple[Any, str]] = []
    for wp_id, name, typ, grund, dauer in zeilen:
        m = _NAME.match(name or "")
        if not m or typ != "technical_stop" or not dauer:
            continue
        art = _ART[m.group(1)]
        if art == "tech" and grund not in (None, ""):
            continue
        if art == "break" and (grund != "rest" or dauer < _LENKPAUSE_MIN):
            continue
        if art == "daily_rest" and (grund != "rest" or dauer != _TAGESRUHE_MIN):
            continue
        treffer.append((wp_id, art))
    return treffer


def upgrade() -> None:
    op.add_column("waypoints", sa.Column("vorschlag_art", sa.String(20), nullable=True))

    bind = op.get_bind()
    zeilen = bind.execute(
        sa.text("SELECT id, name, type, halt_purpose, hold_duration_min FROM waypoints")
    ).fetchall()
    for art in ("tech", "break", "daily_rest"):
        ids = [wp_id for wp_id, a in vorschlaege(tuple(z) for z in zeilen) if a == art]
        if ids:
            bind.execute(
                sa.text("UPDATE waypoints SET vorschlag_art = :art WHERE id IN :ids")
                .bindparams(sa.bindparam("ids", expanding=True)),
                {"art": art, "ids": ids},
            )


def downgrade() -> None:
    op.drop_column("waypoints", "vorschlag_art")
