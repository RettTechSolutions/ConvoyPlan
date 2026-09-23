"""Ein Fahrzeug sendet von genau einem Gerät (services/belegung.py).

Gemeldet war: den KdoW in der App gewählt, und im Browser ließ er sich noch
einmal wählen. Geprüft wird die Entscheidung ohne Netz und mit gestellter Uhr —
und die Zusage, die man der Oberfläche nicht ansieht: ältere Clients, die keine
Kennung mitschicken, werden nie abgewiesen und bekommen nie einen Nachrichtentyp
zu sehen, den sie nicht kennen.
"""

import pytest

from app.services import belegung as belegung_modul
from app.services.belegung import ABLAUF_S, Belegungen, kennung_pruefen
from app.services.tracking import TrackingManager

KONVOI = "k1"
KDOW = "v-kdow"
ELW = "v-elw"
APP = "app-geraet-1"
WEB = "web-tab-0001"


class Uhr:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def uhr():
    return Uhr()


@pytest.fixture
def b(uhr):
    return Belegungen(uhr=uhr)


def test_wer_zuerst_waehlt_haelt_das_fahrzeug(b):
    assert b.beanspruchen(KONVOI, KDOW, APP) == "neu"
    assert b.beanspruchen(KONVOI, KDOW, WEB) == "fremd"


def test_das_eigene_geraet_erneuert_statt_abgewiesen_zu_werden(b):
    b.beanspruchen(KONVOI, KDOW, APP)
    assert b.beanspruchen(KONVOI, KDOW, APP) == "erneuert"


def test_andere_fahrzeuge_bleiben_waehlbar(b):
    b.beanspruchen(KONVOI, KDOW, APP)
    assert b.beanspruchen(KONVOI, ELW, WEB) == "neu"


def test_belegung_gilt_je_verband(b):
    b.beanspruchen(KONVOI, KDOW, APP)
    assert b.beanspruchen("k2", KDOW, WEB) == "neu"


def test_ein_funkloch_kuerzer_als_der_ablauf_macht_nicht_frei(b, uhr):
    b.beanspruchen(KONVOI, KDOW, APP)
    uhr.t += ABLAUF_S - 1
    assert b.beanspruchen(KONVOI, KDOW, WEB) == "fremd"


def test_jeder_frame_verlaengert_die_belegung(b, uhr):
    b.beanspruchen(KONVOI, KDOW, APP)
    uhr.t += ABLAUF_S - 1
    b.beanspruchen(KONVOI, KDOW, APP)
    uhr.t += ABLAUF_S - 1
    assert b.beanspruchen(KONVOI, KDOW, WEB) == "fremd"


def test_ein_verstummtes_geraet_blockiert_nicht_fuer_immer(b, uhr):
    b.beanspruchen(KONVOI, KDOW, APP)
    uhr.t += ABLAUF_S + 1
    assert b.beanspruchen(KONVOI, KDOW, WEB) == "neu"


def test_ablaufen_nennt_die_frei_gewordenen_fahrzeuge(b, uhr):
    b.beanspruchen(KONVOI, KDOW, APP)
    uhr.t += 10
    b.beanspruchen(KONVOI, ELW, WEB)
    uhr.t += ABLAUF_S - 5
    assert b.ablaufen(KONVOI) == [KDOW]
    assert b.belegte(KONVOI) == [ELW]


def test_abwaehlen_gibt_sofort_frei(b):
    b.beanspruchen(KONVOI, KDOW, APP)
    assert b.freigeben(KONVOI, KDOW, APP) is True
    assert b.beanspruchen(KONVOI, KDOW, WEB) == "neu"


def test_ein_fremdes_geraet_kann_nichts_freigeben(b):
    """Sonst reichte ein ``freigeben``-Frame, um jemandem sein Fahrzeug wegzunehmen."""
    b.beanspruchen(KONVOI, KDOW, APP)
    assert b.freigeben(KONVOI, KDOW, WEB) is False
    assert b.beanspruchen(KONVOI, KDOW, WEB) == "fremd"


def test_die_fuehrung_gibt_ohne_ansehen_des_halters_frei(b):
    b.beanspruchen(KONVOI, KDOW, APP)
    assert b.freigeben(KONVOI, KDOW, None) is True
    assert b.belegte(KONVOI) == []


def test_der_stand_verschweigt_die_eigenen_belegungen(b):
    """Nach einem Neuladen ist das eigene Fahrzeug wählbar, nicht „belegt"."""
    b.beanspruchen(KONVOI, KDOW, APP)
    b.beanspruchen(KONVOI, ELW, WEB)
    assert b.belegte(KONVOI, ausser=APP) == [ELW]
    assert b.belegte(KONVOI, ausser=WEB) == [KDOW]


@pytest.mark.parametrize("roh", [None, "", "kurz", "x" * 65, "mit leerzeichen!", "a/b/c/d/e/f"])
def test_unbrauchbare_kennung_gilt_als_aelterer_client(roh):
    assert kennung_pruefen(roh) is None


def test_brauchbare_kennung_bleibt_wie_sie_ist():
    assert kennung_pruefen("0f3c2a1b-7d9e-4c2a-9b1e-5a6d7c8e9f00") == "0f3c2a1b-7d9e-4c2a-9b1e-5a6d7c8e9f00"


# ── Durchsetzen und Melden (mit gestellten Verbindungen) ─────────────────────


class FakeWs:
    def __init__(self):
        self.gesendet: list[dict] = []

    async def accept(self):
        pass

    async def send_json(self, data):
        self.gesendet.append(data)


@pytest.fixture
def verbunden(monkeypatch, uhr):
    manager = TrackingManager()
    monkeypatch.setattr(belegung_modul, "tracking_manager", manager)
    monkeypatch.setattr(belegung_modul, "belegungen", Belegungen(uhr=uhr))
    return manager


async def test_ein_fremder_frame_wird_verworfen_und_nur_dem_absender_gemeldet(verbunden):
    app, web = FakeWs(), FakeWs()
    await verbunden.connect(KONVOI, app, mit_kennung=True)
    await verbunden.connect(KONVOI, web, mit_kennung=True)

    assert await belegung_modul.pruefen(KONVOI, KDOW, APP, app, durchsetzen=True) is True
    web.gesendet.clear()
    app.gesendet.clear()

    assert await belegung_modul.pruefen(KONVOI, KDOW, WEB, web, durchsetzen=True) is False
    assert web.gesendet == [{"type": "belegung_abgelehnt", "vehicle_id": KDOW}]
    assert app.gesendet == []


async def test_eine_neue_belegung_erfahren_alle_mit_kennung(verbunden):
    app, web = FakeWs(), FakeWs()
    await verbunden.connect(KONVOI, app, mit_kennung=True)
    await verbunden.connect(KONVOI, web, mit_kennung=True)

    await belegung_modul.pruefen(KONVOI, KDOW, APP, app, durchsetzen=True)
    meldung = {"type": "belegung", "vehicle_id": KDOW, "belegt": True}
    assert meldung in web.gesendet

    await belegung_modul.freigeben(KONVOI, KDOW, APP)
    assert web.gesendet[-1] == {"type": "belegung", "vehicle_id": KDOW, "belegt": False}


async def test_ein_aelterer_client_wird_nie_abgewiesen(verbunden):
    """Eine App aus dem Store, die noch nicht aktualisiert ist, sendet im Einsatz weiter."""
    app, alt = FakeWs(), FakeWs()
    await verbunden.connect(KONVOI, app, mit_kennung=True)
    await verbunden.connect(KONVOI, alt, mit_kennung=False)
    await belegung_modul.pruefen(KONVOI, KDOW, APP, app, durchsetzen=True)

    assert await belegung_modul.pruefen(KONVOI, KDOW, "alt-1", alt, durchsetzen=False) is True
    assert alt.gesendet == []


async def test_was_ein_aelterer_client_sendet_belegt_das_fahrzeug(verbunden):
    alt, web = FakeWs(), FakeWs()
    await verbunden.connect(KONVOI, alt, mit_kennung=False)
    await verbunden.connect(KONVOI, web, mit_kennung=True)

    await belegung_modul.pruefen(KONVOI, KDOW, "alt-1", alt, durchsetzen=False)
    assert await belegung_modul.pruefen(KONVOI, KDOW, WEB, web, durchsetzen=True) is False


async def test_ein_aelterer_client_bekommt_keinen_unbekannten_nachrichtentyp(verbunden):
    """Die angemeldete Weboberfläche las früher jede unbekannte Nachricht als Position."""
    app, alt = FakeWs(), FakeWs()
    await verbunden.connect(KONVOI, app, mit_kennung=True)
    await verbunden.connect(KONVOI, alt, mit_kennung=False)

    await belegung_modul.pruefen(KONVOI, KDOW, APP, app, durchsetzen=True)
    await belegung_modul.freigeben(KONVOI, KDOW, APP)
    assert alt.gesendet == []


async def test_eine_neue_verbindung_bekommt_den_stand_ohne_die_eigenen(verbunden):
    app, web = FakeWs(), FakeWs()
    await verbunden.connect(KONVOI, app, mit_kennung=True)
    await belegung_modul.pruefen(KONVOI, KDOW, APP, app, durchsetzen=True)
    await belegung_modul.pruefen(KONVOI, ELW, WEB, None, durchsetzen=True)

    await belegung_modul.stand_senden(KONVOI, WEB, web)
    assert web.gesendet == [{"type": "belegungen", "vehicle_ids": [KDOW]}]


async def test_abgelaufene_belegung_wird_als_frei_gemeldet(verbunden, uhr):
    app, web = FakeWs(), FakeWs()
    await verbunden.connect(KONVOI, app, mit_kennung=True)
    await verbunden.connect(KONVOI, web, mit_kennung=True)
    await belegung_modul.pruefen(KONVOI, KDOW, APP, app, durchsetzen=True)

    uhr.t += ABLAUF_S + 1
    assert await belegung_modul.pruefen(KONVOI, ELW, WEB, web, durchsetzen=True) is True
    assert {"type": "belegung", "vehicle_id": KDOW, "belegt": False} in app.gesendet
