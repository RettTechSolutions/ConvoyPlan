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
    assert text == "stand=1800000000\nnutzer=3\ndemo=1\nfahrer=0\ntracker=0\n"
    mit_fahrern = anwesenheit.meldung(0, 0, 1800000000, im_anlauf=False, vorher=None, fahrer=2)
    assert anwesenheit.lesen(mit_fahrern)["fahrer"] == "2"
    mit_trackern = anwesenheit.meldung(0, 0, 1800000000, im_anlauf=False, vorher=None, tracker=3)
    assert anwesenheit.lesen(mit_trackern)["tracker"] == "3"


def test_nach_neustart_nicht_weniger_als_zuletzt_gemeldet():
    # Die Registry ist nach einem Deploy leer; ohne Anlauf stünde sofort
    # „niemand da" in der Datei und der nächste Build käme gleich hinterher.
    vorher = "stand=1\nnutzer=4\ndemo=2\nfahrer=3\n"
    text = anwesenheit.meldung(1, 0, 100, im_anlauf=True, vorher=vorher)
    assert anwesenheit.lesen(text) == {
        "stand": "100", "nutzer": "4", "demo": "2", "fahrer": "3", "tracker": "0",
    }
    nach_anlauf = anwesenheit.meldung(1, 0, 400, im_anlauf=False, vorher=vorher)
    assert anwesenheit.lesen(nach_anlauf)["nutzer"] == "1"


def test_unlesbare_vorherige_meldung_stoert_nicht():
    text = anwesenheit.meldung(0, 0, 100, im_anlauf=True, vorher="kaputt\nnutzer=x\n")
    assert text == "stand=100\nnutzer=0\ndemo=0\nfahrer=0\ntracker=0\n"


def test_tracker_kommen_aus_der_datenbank_und_kennen_keinen_anlauf():
    # Nach einem Neustart ist die Datenbank sofort vollständig; die letzte
    # Meldung zählt für Tracker nicht.
    text = anwesenheit.meldung(0, 0, 100, im_anlauf=True, vorher="tracker=5\n", tracker=1)
    assert anwesenheit.lesen(text)["tracker"] == "1"


def test_tracker_frist_wie_der_vorrang_vor_dem_telefon():
    from app.services.positionsquelle import VORRANG_S

    assert anwesenheit.TRACKER_FRIST_S == VORRANG_S


def test_zustand_des_updaters_fuers_panel():
    text = (
        "seit=1800000000\nzuletzt=1800000600\nziel=nightly abc\n"
        "nutzer=2\ndemo=1\nfahrer=4\ntracker=3\n"
    )
    zustand = anwesenheit.zurueckgehalten_aus(text, 1800000700)
    assert zustand == {
        "since": datetime.fromtimestamp(1800000000, tz=timezone.utc).isoformat(),
        "users": 2,
        "demo_users": 1,
        "drivers": 4,
        "trackers": 3,
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


class Uhr:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


K = "konvoi-1"
LAUFEND = {K}


def test_fahrer_link_zaehlt_solange_er_verbunden_ist():
    uhr = Uhr()
    links = anwesenheit.FahrerLinks(uhr=uhr, nachlauf_s=300)
    links.verbunden("app-1", K)
    uhr.t += 3600  # sendet nichts, ist aber verbunden
    assert links.anzahl(LAUFEND) == 1


def test_fahrer_link_zaehlt_nach_dem_abriss_noch_fuenf_minuten():
    # Das Funkloch ist der Normalfall — wie bei der Belegung.
    uhr = Uhr()
    links = anwesenheit.FahrerLinks(uhr=uhr, nachlauf_s=300)
    links.verbunden("app-1", K)
    links.getrennt("app-1", K)
    uhr.t += 299
    assert links.anzahl(LAUFEND) == 1
    uhr.t += 2
    assert links.anzahl(LAUFEND) == 0
    assert links.konvois() == set()


def test_ein_geraet_mit_zwei_verbindungen_zaehlt_einmal():
    uhr = Uhr()
    links = anwesenheit.FahrerLinks(uhr=uhr, nachlauf_s=300)
    links.verbunden("app-1", K)
    links.verbunden("app-1", K)
    links.verbunden("web-1", K)
    assert links.anzahl(LAUFEND) == 2
    links.getrennt("app-1", K)
    uhr.t += 600
    assert links.anzahl(LAUFEND) == 2  # die zweite Verbindung von app-1 steht noch
    links.getrennt("app-1", K)
    links.getrennt("web-1", K)
    uhr.t += 301
    assert links.anzahl(LAUFEND) == 0


def test_ein_frame_verlaengert_den_nachlauf():
    uhr = Uhr()
    links = anwesenheit.FahrerLinks(uhr=uhr, nachlauf_s=300)
    links.verbunden("app-1", K)
    links.getrennt("app-1", K)
    uhr.t += 200
    links.aktiv("app-1", K)
    uhr.t += 200
    assert links.anzahl(LAUFEND) == 1


def test_nur_laufende_konvois_zaehlen():
    links = anwesenheit.FahrerLinks()
    links.verbunden("app-1", "geplant")
    links.verbunden("app-2", K)
    assert links.konvois() == {"geplant", K}
    assert links.anzahl(LAUFEND) == 1
    assert links.anzahl(set()) == 0
    # Läuft der geplante später an, zählt er beim nächsten Schreiben mit.
    assert links.anzahl({"geplant", K}) == 2


def test_ein_geraet_in_zwei_laufenden_konvois_zaehlt_einmal():
    links = anwesenheit.FahrerLinks()
    links.verbunden("app-1", K)
    links.verbunden("app-1", "konvoi-2")
    assert links.anzahl({K, "konvoi-2"}) == 1


def test_schreiben_zaehlt_fahrer_links(monkeypatch, tmp_path):
    ziel = tmp_path / "anwesenheit"
    monkeypatch.setattr(anwesenheit, "ANWESENHEIT_FILE", str(ziel))
    monkeypatch.setattr(anwesenheit, "ANLAUF_S", 0)
    links = anwesenheit.FahrerLinks()
    links.verbunden("app-1", K)
    links.verbunden("app-2", "geplant")
    monkeypatch.setattr(anwesenheit, "fahrer_links", links)
    activity.reset()
    anwesenheit.schreiben(LAUFEND)
    assert anwesenheit.lesen(ziel.read_text())["fahrer"] == "1"
    anwesenheit.schreiben()
    assert anwesenheit.lesen(ziel.read_text())["fahrer"] == "0"


def test_schreiben_traegt_die_tracker_ein(monkeypatch, tmp_path):
    ziel = tmp_path / "anwesenheit"
    monkeypatch.setattr(anwesenheit, "ANWESENHEIT_FILE", str(ziel))
    monkeypatch.setattr(anwesenheit, "ANLAUF_S", 0)
    monkeypatch.setattr(anwesenheit, "fahrer_links", anwesenheit.FahrerLinks())
    activity.reset()
    anwesenheit.schreiben(tracker=2)
    assert anwesenheit.lesen(ziel.read_text())["tracker"] == "2"
