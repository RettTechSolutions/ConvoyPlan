"""Automatische Updates warten, solange Nutzer angemeldet sind.

Die Entscheidung trifft der Updater (``docker/updater/anwesenheit.sh``, geprüft
von ``docker/updater/tests/test_anwesenheit.sh``). Hier geht es um die Hälfte
des Backends: was es dem Updater meldet und wie es dessen Zustand liest.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.services import activity, anwesenheit


def _eintrag(kind: str) -> activity.UserActivity:
    jetzt = datetime.now(timezone.utc)
    return activity.UserActivity(uuid.uuid4(), None, jetzt, jetzt, 1, kind)


def test_superadmins_zaehlen_nicht():
    entries = [
        _eintrag(activity.KIND_MEMBER),
        _eintrag(activity.KIND_MEMBER),
        _eintrag(activity.KIND_DEMO),
        _eintrag(activity.KIND_ADMIN),
    ]
    assert anwesenheit.zaehlen(entries) == (2, 1)


def test_meldung_im_format_des_updaters():
    text = anwesenheit.meldung(3, 1, 1800000000, im_anlauf=False, vorher=None)
    assert text == "stand=1800000000\nnutzer=3\ndemo=1\n"


def test_nach_neustart_nicht_weniger_als_zuletzt_gemeldet():
    # Die Registry ist nach einem Deploy leer; ohne Anlauf stünde sofort
    # „niemand da" in der Datei und der nächste Build käme gleich hinterher.
    vorher = "stand=1\nnutzer=4\ndemo=2\n"
    text = anwesenheit.meldung(1, 0, 100, im_anlauf=True, vorher=vorher)
    assert anwesenheit.lesen(text) == {"stand": "100", "nutzer": "4", "demo": "2"}
    nach_anlauf = anwesenheit.meldung(1, 0, 400, im_anlauf=False, vorher=vorher)
    assert anwesenheit.lesen(nach_anlauf)["nutzer"] == "1"


def test_unlesbare_vorherige_meldung_stoert_nicht():
    text = anwesenheit.meldung(0, 0, 100, im_anlauf=True, vorher="kaputt\nnutzer=x\n")
    assert text == "stand=100\nnutzer=0\ndemo=0\n"


def test_zustand_des_updaters_fuers_panel():
    text = "seit=1800000000\nzuletzt=1800000600\nziel=nightly abc\nnutzer=2\ndemo=1\n"
    zustand = anwesenheit.zurueckgehalten_aus(text, 1800000700)
    assert zustand == {
        "since": datetime.fromtimestamp(1800000000, tz=timezone.utc).isoformat(),
        "users": 2,
        "demo_users": 1,
    }


def test_alter_zustand_gilt_nicht_mehr():
    # Ein Updater, der nicht mehr hält (oder nicht mehr läuft), schreibt die
    # Datei nicht fort — dann steht im Panel auch nichts mehr davon.
    text = "seit=1800000000\nzuletzt=1800000000\nnutzer=2\ndemo=0\n"
    assert anwesenheit.zurueckgehalten_aus(text, 1800000000 + anwesenheit.HOLD_FRISCH_S + 1) is None
    assert anwesenheit.zurueckgehalten_aus("", 1800000000) is None


def test_schreiben_ohne_volume_wirft_nicht(monkeypatch, tmp_path):
    monkeypatch.setattr(anwesenheit, "ANWESENHEIT_FILE", str(tmp_path / "fehlt" / "anwesenheit"))
    anwesenheit.schreiben()


def test_schreiben_zaehlt_die_registry(monkeypatch, tmp_path):
    ziel = tmp_path / "anwesenheit"
    monkeypatch.setattr(anwesenheit, "ANWESENHEIT_FILE", str(ziel))
    monkeypatch.setattr(anwesenheit, "ANLAUF_S", 0)
    activity.reset()
    try:
        activity.touch(uuid.uuid4(), kind=activity.KIND_MEMBER)
        activity.touch(uuid.uuid4(), kind=activity.KIND_DEMO)
        activity.touch(uuid.uuid4(), kind=activity.KIND_ADMIN)
        anwesenheit.schreiben()
    finally:
        activity.reset()
    werte = anwesenheit.lesen(ziel.read_text())
    assert (werte["nutzer"], werte["demo"]) == ("1", "1")
