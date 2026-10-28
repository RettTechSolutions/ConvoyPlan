"""Tests für den Backfill in Migration 0074.

Die Migration entscheidet, welche Wegpunkte des Bestands als unberührt
übernommene Halte-Vorschläge gelten — die darf „Halte neu verteilen" später
ersetzen. Trifft sie daneben, verschwindet ein Halt, den jemand bewusst so
gesetzt hat. Deshalb ohne Datenbank geprüft, wie bei 0046.
"""
import importlib.util
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic" / "versions" / "0074_wegpunkt_vorschlag.py"
)

_spec = importlib.util.spec_from_file_location("migration_0074", MIGRATION)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def _zeile(wp_id, name, typ="technical_stop", grund=None, dauer=15):
    return (wp_id, name, typ, grund, dauer)


def test_die_drei_arten_aus_der_empfehlung():
    zeilen = [
        _zeile("th", "Technischer Halt (km 126.1)"),
        _zeile("lp", "Lenkpause (km 252.2)", grund="rest", dauer=45),
        _zeile("tr", "Tagesruhezeit (km 535.8)", grund="rest", dauer=660),
        _zeile("ganz", "Lenkpause (km 788)", grund="rest", dauer=45),
    ]
    assert m.vorschlaege(zeilen) == [("th", "tech"), ("lp", "break"), ("tr", "daily_rest"), ("ganz", "break")]


def test_umbenannt_ist_eigener_halt():
    assert m.vorschlaege([_zeile("a", "Technischer Halt Brennersee")]) == []
    assert m.vorschlaege([_zeile("a", "Technischer Halt (km 126.1) – Parkplatz")]) == []


def test_tankstopp_ist_kein_halt_vorschlag():
    # Der Tankstopp heißt nach der Tankstelle und trägt `fuel`.
    assert m.vorschlaege([_zeile("a", "Technischer Halt (km 126.1)", grund="fuel")]) == []


def test_geaenderte_dauer_oder_art_ist_eigener_halt():
    assert m.vorschlaege([
        _zeile("a", "Tagesruhezeit (km 535.8)", grund="rest", dauer=600),
        _zeile("b", "Lenkpause (km 252.2)", grund="rest", dauer=30),
        _zeile("c", "Lenkpause (km 252.2)", typ="stop", grund="rest", dauer=45),
        _zeile("d", "Technischer Halt (km 126.1)", dauer=0),
    ]) == []


def test_lange_lenkpause_bei_grossem_verband_zaehlt():
    # Ab 10 Fahrzeugen dauert der TH 60 min, die Lenkpause nimmt die längere Dauer.
    assert m.vorschlaege([_zeile("a", "Lenkpause (km 252.2)", grund="rest", dauer=60)]) == [("a", "break")]
