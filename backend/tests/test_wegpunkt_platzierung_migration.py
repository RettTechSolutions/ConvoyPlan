"""Tests für den Backfill in Migration 0045.

Die Migration schreibt gespeicherte Nutzdaten um: sie entscheidet, welche
Wegpunkte des Bestands als „noch nicht einsortiert" gelten. Trifft sie daneben,
wandert bei der nächsten Routenberechnung ein Halt, den jemand bewusst gesetzt
hat — oder ein angehängter Tankstopp bleibt am Listenende und erzeugt den
Umweg, gegen den es die Einordnung gibt. Die Auswahl ist deshalb als Funktion
herausgezogen und wird hier ohne Datenbank geprüft (wie bei 0039).
"""
import importlib.util
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic" / "versions" / "0045_wegpunkt_platzierung.py"
)

_spec = importlib.util.spec_from_file_location("migration_0045", MIGRATION)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

KONVOI = "konvoi-1"


def _zeile(wp_id, order_index, typ="waypoint", convoy_id=KONVOI):
    return (wp_id, convoy_id, typ, order_index)


def test_angehaengter_halt_gilt_als_unplatziert():
    zeilen = [
        _zeile("a", 0),
        _zeile("b", 1),
        _zeile("th", 2, "technical_stop"),
    ]
    assert m.unplatzierte(zeilen) == ["th"]


def test_der_ganze_lauf_am_ende_zaehlt():
    zeilen = [
        _zeile("a", 0),
        _zeile("th1", 1, "technical_stop"),
        _zeile("th2", 2, "technical_stop"),
        _zeile("th3", 3, "technical_stop"),
    ]
    assert sorted(m.unplatzierte(zeilen)) == ["th1", "th2", "th3"]


def test_ein_halt_mit_wegpunkt_dahinter_bleibt_unangetastet():
    """Den hat jemand dorthin gesetzt — die alte Regel ließ ihn auch stehen."""
    zeilen = [
        _zeile("a", 0),
        _zeile("th", 1, "technical_stop"),
        _zeile("b", 2),
    ]
    assert m.unplatzierte(zeilen) == []


def test_nur_der_lauf_am_ende_zaehlt_nicht_jeder_halt():
    zeilen = [
        _zeile("th_mitte", 0, "technical_stop"),
        _zeile("a", 1),
        _zeile("th_ende", 2, "technical_stop"),
    ]
    assert m.unplatzierte(zeilen) == ["th_ende"]


def test_die_reihenfolge_entscheidet_nicht_die_lesereihenfolge():
    """Die Abfrage liefert ungeordnet; sortiert wird über `order_index`."""
    zeilen = [
        _zeile("th", 2, "technical_stop"),
        _zeile("b", 1),
        _zeile("a", 0),
    ]
    assert m.unplatzierte(zeilen) == ["th"]


def test_jeder_konvoi_wird_fuer_sich_betrachtet():
    zeilen = [
        _zeile("a", 0, convoy_id="k1"),
        _zeile("th1", 1, "technical_stop", convoy_id="k1"),
        _zeile("th2", 0, "technical_stop", convoy_id="k2"),
        _zeile("b", 1, convoy_id="k2"),
    ]
    assert m.unplatzierte(zeilen) == ["th1"]


def test_ohne_wegpunkte_passiert_nichts():
    assert m.unplatzierte([]) == []
