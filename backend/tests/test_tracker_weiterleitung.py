"""Weiterleitung über BLE: Gerät → Begleit-App → Instanz → signierte Anweisung zurück.

Was hier zugesagt wird:

- Ein Rahmen, den die App mit ihrem Fahrer-Link abliefert, wirkt wie der direkte
  Aufruf: Fixes landen im laufenden Konvoi, die Anweisung kommt signiert zurück, der
  Weg steht als ``ble`` am Gerät. Firmware, Wurzeln, Schlüssel und der Nahfunk-Zugang
  sind darin immer null.
- Die App kann nichts fälschen: geänderter Rahmen, fremder Schlüssel, fremdes Gerät,
  Gerät einer anderen Organisation, Link ohne ``driver``, widerrufen oder ohne
  Sitzungstoken — alles dieselbe 404.
- Ein Rahmen gilt einmal: dieselbe oder eine kleinere ``seq`` ist 409, auch wenn zwei
  Apps ihn gleichzeitig abliefern.
- Ein gesperrtes Gerät erfährt es auch über BLE (``status: 401`` in der signierten
  Antwort), ein unbrauchbarer Körper ebenso (``400``).
- Ohne Lizenz verhält sich die Weiterleitung wie der direkte Weg: ``schweigen``, kein 402.
- Den Schlüssel gibt es nur direkt: bei ``einloesen`` und in ``hallo``, wenn die
  gemeldete Kennung abweicht — nie ohne das Feld, nie in ``positionen``, nie über BLE.
- ``signal_dbm`` gilt nur über Mobilfunk; ein unbekannter Weg wird verworfen.
"""
import asyncio
import base64
import json
import uuid

import pytest
from sqlalchemy import delete, select, update

from app.database import AsyncSessionLocal
from app.models.convoy import Convoy
from app.models.ortungsgeraet import Ortungsgeraet
from app.models.share_link import ConvoyShareLink
from app.services import belegung as belegung_modul
from app.services import positionsquelle as pq
from app.services import share_links as sl
from app.services import tracker_ble as tb
from app.services.belegung import Belegungen
from app.services.positionsquelle import Positionsquellen
from tests.aktionsseite_fixtures import client, h, reset_db_engine  # noqa: F401
from tests.test_tracker_bake import _link
from tests.test_tracker_geraete import (  # noqa: F401
    _anlegen,
    _einloesen,
    _fix,
    _position,
    ohne_lizenz,
    org,
)

INSTANZ = "http://test"


@pytest.fixture(autouse=True)
def frische_quellen(monkeypatch):
    monkeypatch.setattr(pq, "positionsquellen", Positionsquellen())


class Geraet:
    """Die Geräteseite der Weiterleitung, wie die Firmware sie tut."""

    def __init__(self, geraet_id: str, schluessel: str, kopf: dict):
        self.id = geraet_id
        self.schluessel = base64.b64decode(schluessel)
        self.kopf = kopf
        self.seq = 1 << 32

    def rahmen(self, art: str, koerper: dict, seq: int | None = None, schluessel: bytes | None = None) -> dict:
        if seq is None:
            self.seq += 1
            seq = self.seq
        nutzlast = base64.b64encode(json.dumps({"netz": "ble", **koerper}).encode()).decode()
        r = tb.Rahmen(geraet=self.id, seq=seq, art=art, instanz=INSTANZ, nutzlast=nutzlast, mac="")
        mac = tb.rahmen_mac(schluessel or self.schluessel, r)
        return {"geraet": r.geraet, "seq": r.seq, "art": r.art, "instanz": r.instanz, "nutzlast": nutzlast, "mac": mac}

    def lesen(self, rahmen: dict, antwort: dict) -> dict:
        """Wie das Gerät die Antwort prüft: ``seq`` und Signatur, dann der Inhalt."""
        assert antwort["seq"] == rahmen["seq"]
        erwartet = tb.antwort_mac(self.schluessel, self.id, rahmen["seq"], antwort["antwort"])
        assert antwort["mac"] == erwartet, "Antwort nicht von der Instanz signiert"
        return json.loads(base64.b64decode(antwort["antwort"]))


@pytest.fixture
async def aufbau(org, client):  # noqa: F811
    """Ein eingerichteter Tracker am HLF und ein Fahrer-Link auf den laufenden Konvoi."""
    geraet = await _anlegen(client, org)
    eingeloest = await _einloesen(client, geraet["code"])
    slug = await _link(org.konvoi, org.users[0])
    yield org, Geraet(eingeloest["geraet_id"], eingeloest["schluessel"], h(eingeloest["token"])), slug
    async with AsyncSessionLocal() as db:
        await db.execute(delete(ConvoyShareLink).where(ConvoyShareLink.created_by_id.in_(org.users)))
        await db.execute(delete(Convoy).where(Convoy.organization_id == org.andere_id))
        await db.commit()


async def _zeile(client, org) -> dict:
    return (await client.get("/api/org/geraete", headers=h(org.admin))).json()[0]


class TestGanzerWeg:
    async def test_positionen_ueber_die_app(self, client, aufbau):
        org, geraet, slug = aufbau
        rahmen = geraet.rahmen("positionen", {"akku_prozent": 84, "extern": False, "fixes": [_fix(5, 11.2)]})
        r = await client.post(f"/api/track/{slug}/tracker", json=rahmen)
        assert r.status_code == 200, r.text
        inhalt = geraet.lesen(rahmen, r.json())
        assert inhalt["status"] == 200
        koerper = inhalt["koerper"]
        assert (koerper["angenommen"], koerper["verworfen"], koerper["modus"]) == (1, 0, "senden")
        assert koerper["firmware"] is None
        assert "schluessel" not in koerper and "wurzeln" not in koerper
        # Wie direkt: Position vom Tracker im laufenden Konvoi.
        pos = await _position(org.konvoi, org.hlf)
        assert pos is not None and pos.lon == 11.2 and pos.quelle == "tracker"
        zeile = await _zeile(client, org)
        assert zeile["netz"] == "ble" and zeile["akku_prozent"] == 84
        tracker = (await client.get(f"/api/convoys/{org.konvoi}/tracker", headers=h(org.admin))).json()
        assert tracker[0]["netz"] == "ble"

    async def test_hallo_ueber_die_app_ohne_firmware_wurzeln_schluessel(self, client, aufbau, monkeypatch):
        from app.api.routes import geraete as geraete_routen

        org, geraet, slug = aufbau

        async def angebot(*_):
            return {"version": "9.9.9", "url": "x", "sha256": "0" * 64, "groesse": 1}

        monkeypatch.setattr(geraete_routen.firmware_angebot, "fuer_geraet", angebot)
        rahmen = geraet.rahmen(
            "hallo",
            {"grund": "bewegung", "signal_dbm": -95, "schluessel_kennung": "", "wurzeln_sha256": "0" * 64},
        )
        r = await client.post(f"/api/track/{slug}/tracker", json=rahmen)
        assert r.status_code == 200, r.text
        inhalt = geraet.lesen(rahmen, r.json())
        assert inhalt["status"] == 200
        k = inhalt["koerper"]
        assert k["modus"] == "senden"
        assert (k["firmware"], k["wurzeln"], k["schluessel"]) == (None, None, None)
        zeile = await _zeile(client, org)
        # Über BLE kein RSRP.
        assert zeile["netz"] == "ble" and zeile["signal_dbm"] is None
        # Direkt hätte es Firmware und Schlüssel gegeben.
        direkt = (await client.post("/api/geraete/hallo", json={"schluessel_kennung": ""}, headers=geraet.kopf)).json()
        assert direkt["firmware"] is not None and direkt["schluessel"] is not None

    async def test_kein_nahfunk_zugang_ueber_die_app(self, client, aufbau, monkeypatch):
        """Der Nahfunk-Zugang ist Schlüsselmaterial: direkt ja, über BLE nie.

        Gerät im laufenden Konvoi, Fahrzeug von einer App belegt — direkt bekäme der
        Tracker `nahfunk` mit Schlüssel, weitergeleitet steht dort in `hallo` und in
        `positionen` null."""
        org, geraet, slug = aufbau
        belegungen = Belegungen()
        monkeypatch.setattr(belegung_modul, "belegungen", belegungen)
        belegungen.beanspruchen(str(org.konvoi), str(org.hlf), "app-besatzung")

        direkt = (await client.post("/api/geraete/hallo", json={}, headers=geraet.kopf)).json()
        assert direkt["modus"] == "senden"
        assert direkt["nahfunk"] is not None and direkt["nahfunk"]["schluessel"]
        material = {direkt["nahfunk"]["schluessel"], direkt["nahfunk"]["kennung"]}

        for art, koerper in (
            ("hallo", {"grund": "bewegung", "schluessel_kennung": ""}),
            ("positionen", {"fixes": [_fix(5, 11.2)]}),
        ):
            rahmen = geraet.rahmen(art, koerper)
            r = await client.post(f"/api/track/{slug}/tracker", json=rahmen)
            assert r.status_code == 200, r.text
            inhalt = geraet.lesen(rahmen, r.json())
            assert inhalt["status"] == 200
            k = inhalt["koerper"]
            assert k["modus"] == "senden", art
            assert k["nahfunk"] is None, art
            assert k.get("schluessel") is None and k["firmware"] is None, art
            text = json.dumps(k)
            assert not any(m in text for m in material), art

    async def test_geraet_muss_nicht_im_konvoi_des_links_fahren(self, client, aufbau):
        org, geraet, _ = aufbau
        # Link auf den Konvoi in Planung: das Gerät fährt im anderen, laufenden.
        slug = await _link(org.zweiter, org.users[0])
        rahmen = geraet.rahmen("positionen", {"fixes": [_fix(5, 11.3)]})
        r = await client.post(f"/api/track/{slug}/tracker", json=rahmen)
        assert r.status_code == 200, r.text
        assert geraet.lesen(rahmen, r.json())["koerper"]["angenommen"] == 1
        assert (await _position(org.konvoi, org.hlf)).lon == 11.3
        assert await _position(org.zweiter, org.hlf) is None

    async def test_unbrauchbarer_koerper_ist_eine_signierte_400(self, client, aufbau):
        _, geraet, slug = aufbau
        rahmen = geraet.rahmen("positionen", {"fixes": "keine Liste"})
        r = await client.post(f"/api/track/{slug}/tracker", json=rahmen)
        assert r.status_code == 200, r.text
        inhalt = geraet.lesen(rahmen, r.json())
        assert inhalt["status"] == 400

    async def test_gesperrtes_geraet_erfaehrt_es_ueber_ble(self, client, aufbau):
        org, geraet, slug = aufbau
        r = await client.put(
            f"/api/org/geraete/{geraet.id}",
            json={"name": "Tracker HLF", "vehicle_id": str(org.hlf), "aktiv": False},
            headers=h(org.admin),
        )
        assert r.status_code == 200, r.text
        rahmen = geraet.rahmen("positionen", {"fixes": [_fix(5, 11.4)]})
        r = await client.post(f"/api/track/{slug}/tracker", json=rahmen)
        assert r.status_code == 200, r.text
        assert geraet.lesen(rahmen, r.json())["status"] == 401
        assert await _position(org.konvoi, org.hlf) is None
        # Auch die `seq` ist verbraucht: die Antwort lässt sich nicht wieder abspielen.
        assert (await client.post(f"/api/track/{slug}/tracker", json=rahmen)).status_code == 409

    async def test_ohne_lizenz_schweigen_statt_402(self, client, aufbau, ohne_lizenz):  # noqa: F811
        org, geraet, slug = aufbau
        rahmen = geraet.rahmen("positionen", {"fixes": [_fix(5, 11.5)]})
        r = await client.post(f"/api/track/{slug}/tracker", json=rahmen)
        assert r.status_code == 200, r.text
        k = geraet.lesen(rahmen, r.json())["koerper"]
        assert (k["modus"], k["angenommen"], k["verworfen"]) == ("schweigen", 0, 1)
        assert await _position(org.konvoi, org.hlf) is None


class TestFaelschung:
    async def test_geaenderter_rahmen(self, client, aufbau):
        org, geraet, slug = aufbau
        rahmen = geraet.rahmen("positionen", {"fixes": [_fix(5, 11.6)]})
        anders = json.loads(base64.b64decode(rahmen["nutzlast"]))
        anders["fixes"][0]["lon"] = 13.0
        gefaelscht = {**rahmen, "nutzlast": base64.b64encode(json.dumps(anders).encode()).decode()}
        assert (await client.post(f"/api/track/{slug}/tracker", json=gefaelscht)).status_code == 404
        for feld, wert in (("seq", rahmen["seq"] + 1), ("art", "hallo"), ("instanz", "https://x.example.org")):
            r = await client.post(f"/api/track/{slug}/tracker", json={**rahmen, feld: wert})
            assert r.status_code == 404, feld
        assert await _position(org.konvoi, org.hlf) is None
        # Der echte Rahmen geht danach noch: abgelehnte verbrauchen keine `seq`.
        assert (await client.post(f"/api/track/{slug}/tracker", json=rahmen)).status_code == 200

    async def test_fremder_schluessel_unbekanntes_geraet_unbrauchbarer_rahmen(self, client, aufbau):
        _, geraet, slug = aufbau
        fremd = geraet.rahmen("positionen", {"fixes": [_fix(5)]}, schluessel=tb.schluessel_erzeugen())
        unbekannt = {**geraet.rahmen("positionen", {"fixes": [_fix(5)]}), "geraet": str(uuid.uuid4())}
        kaputt = {**geraet.rahmen("positionen", {"fixes": [_fix(5)]}), "geraet": "kein-uuid"}
        antworten = [
            await client.post(f"/api/track/{slug}/tracker", json=koerper)
            for koerper in (fremd, unbekannt, kaputt, {"seq": 1}, [1, 2], None)
        ]
        assert [r.status_code for r in antworten] == [404] * 6
        # Dieselbe Antwort, ob Gerät, Signatur oder Rahmen nicht stimmen.
        assert len({r.text for r in antworten[:3]}) == 1

    async def test_link_einer_fremden_organisation(self, client, aufbau):
        org, geraet, _ = aufbau
        async with AsyncSessionLocal() as db:
            fremder = Convoy(name="Fremd", owner_id=org.users[2], organization_id=org.andere_id, status="running")
            db.add(fremder)
            await db.commit()
            fremder_id = fremder.id
        slug = await _link(fremder_id, org.users[2])
        rahmen = geraet.rahmen("positionen", {"fixes": [_fix(5)]})
        r = await client.post(f"/api/track/{slug}/tracker", json=rahmen)
        assert r.status_code == 404

    async def test_link_ohne_driver_widerrufen_oder_ohne_token(self, client, aufbau):
        org, geraet, _ = aufbau
        nur_sehen = await _link(org.konvoi, org.users[0], scope="track")
        widerrufen = await _link(org.konvoi, org.users[0], revoked=True)
        geschuetzt = await _link(org.konvoi, org.users[0], password_hash=sl.hash_password("geheim123"))
        rahmen = geraet.rahmen("positionen", {"fixes": [_fix(5)]})
        for slug in (nur_sehen, widerrufen, geschuetzt, "gibtsnicht"):
            assert (await client.post(f"/api/track/{slug}/tracker", json=rahmen)).status_code == 404, slug
        r = await client.post(
            f"/api/track/{geschuetzt}/tracker", json=rahmen, headers={"X-Track-Token": sl.issue_session_token(geschuetzt)}
        )
        assert r.status_code == 200, r.text

    async def test_neu_eingerichtet_alter_schluessel_gilt_nicht(self, client, aufbau):
        org, geraet, slug = aufbau
        code = (await client.post(f"/api/org/geraete/{geraet.id}/code", headers=h(org.admin))).json()["code"]
        neu = await _einloesen(client, code)
        assert base64.b64decode(neu["schluessel"]) != geraet.schluessel
        r = await client.post(f"/api/track/{slug}/tracker", json=geraet.rahmen("positionen", {"fixes": [_fix(5)]}))
        assert r.status_code == 404
        # Mit dem neuen Schlüssel geht es, und `seq` zählt von vorn.
        neues = Geraet(neu["geraet_id"], neu["schluessel"], h(neu["token"]))
        r = await client.post(f"/api/track/{slug}/tracker", json=neues.rahmen("positionen", {"fixes": [_fix(5)]}, seq=1))
        assert r.status_code == 200, r.text


class TestWiederholung:
    async def test_dieselbe_oder_kleinere_seq_ist_409(self, client, aufbau):
        org, geraet, slug = aufbau
        erster = geraet.rahmen("positionen", {"fixes": [_fix(20, 11.1)]})
        assert (await client.post(f"/api/track/{slug}/tracker", json=erster)).status_code == 200
        assert (await client.post(f"/api/track/{slug}/tracker", json=erster)).status_code == 409
        aelter = geraet.rahmen("positionen", {"fixes": [_fix(10, 11.7)]}, seq=erster["seq"] - 1)
        assert (await client.post(f"/api/track/{slug}/tracker", json=aelter)).status_code == 409
        assert (await _position(org.konvoi, org.hlf)).lon == 11.1
        weiter = geraet.rahmen("positionen", {"fixes": [_fix(5, 11.8)]})
        assert (await client.post(f"/api/track/{slug}/tracker", json=weiter)).status_code == 200
        assert (await _position(org.konvoi, org.hlf)).lon == 11.8

    async def test_zwei_apps_gleichzeitig_verarbeitet_einmal(self, client, aufbau):
        org, geraet, slug = aufbau
        rahmen = geraet.rahmen("positionen", {"fixes": [_fix(5, 11.9)]})
        antworten = await asyncio.gather(
            *[client.post(f"/api/track/{slug}/tracker", json=rahmen) for _ in range(4)]
        )
        assert sorted(r.status_code for r in antworten) == [200, 409, 409, 409]
        async with AsyncSessionLocal() as db:
            seq = (await db.execute(select(Ortungsgeraet.ble_seq).where(Ortungsgeraet.id == uuid.UUID(geraet.id)))).scalar_one()
        assert seq == rahmen["seq"]


class TestSchluesselImHallo:
    async def test_einloesen_bringt_den_schluessel(self, client, org):  # noqa: F811
        geraet = await _anlegen(client, org)
        eingeloest = await _einloesen(client, geraet["code"])
        assert len(base64.b64decode(eingeloest["schluessel"])) == 32
        # Nicht in der Liste, nicht im Klartext gespeichert.
        zeile = await _zeile(client, org)
        assert "schluessel" not in zeile and eingeloest["schluessel"] not in json.dumps(zeile)
        async with AsyncSessionLocal() as db:
            abgelegt = (await db.execute(select(Ortungsgeraet.schluessel).where(Ortungsgeraet.id == uuid.UUID(geraet["id"])))).scalar_one()
        assert abgelegt and eingeloest["schluessel"] not in abgelegt

    async def test_angebot_nur_bei_abweichender_kennung(self, client, org):  # noqa: F811
        geraet = await _anlegen(client, org)
        eingeloest = await _einloesen(client, geraet["code"])
        kopf = h(eingeloest["token"])
        kennung = tb.kennung(base64.b64decode(eingeloest["schluessel"]))

        async def hallo(**daten) -> dict:
            r = await client.post("/api/geraete/hallo", json=daten, headers=kopf)
            assert r.status_code == 200, r.text
            return r.json()

        # Alte Firmware ohne das Feld: nie.
        assert (await hallo())["schluessel"] is None
        assert (await hallo(schluessel_kennung=kennung))["schluessel"] is None
        assert (await hallo(schluessel_kennung=""))["schluessel"] == eingeloest["schluessel"]
        assert (await hallo(schluessel_kennung="0123456789abcdef"))["schluessel"] == eingeloest["schluessel"]
        # Nie in `positionen`.
        r = await client.post(
            "/api/geraete/positionen", json={"schluessel_kennung": "", "fixes": [_fix(5)]}, headers=kopf
        )
        assert r.status_code == 200 and "schluessel" not in r.json()

    async def test_geraet_von_vor_e14_bekommt_beim_hallo_seinen_ersten(self, client, org):  # noqa: F811
        geraet = await _anlegen(client, org)
        eingeloest = await _einloesen(client, geraet["code"])
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Ortungsgeraet).where(Ortungsgeraet.id == uuid.UUID(geraet["id"])).values(schluessel=None)
            )
            await db.commit()
        kopf = h(eingeloest["token"])
        # Ohne Feld wird keiner erzeugt.
        assert (await client.post("/api/geraete/hallo", json={}, headers=kopf)).json()["schluessel"] is None
        neu = (await client.post("/api/geraete/hallo", json={"schluessel_kennung": ""}, headers=kopf)).json()["schluessel"]
        assert neu and neu != eingeloest["schluessel"]
        # Derselbe beim nächsten Mal, falls die Antwort verloren ging.
        assert (await client.post("/api/geraete/hallo", json={"schluessel_kennung": ""}, headers=kopf)).json()["schluessel"] == neu
        # Und damit geht die Weiterleitung.
        slug = await _link(org.konvoi, org.users[0])
        try:
            g = Geraet(geraet["id"], neu, kopf)
            rahmen = g.rahmen("positionen", {"fixes": [_fix(5, 11.25)]})
            r = await client.post(f"/api/track/{slug}/tracker", json=rahmen)
            assert r.status_code == 200, r.text
            assert g.lesen(rahmen, r.json())["koerper"]["angenommen"] == 1
        finally:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(ConvoyShareLink).where(ConvoyShareLink.slug == slug))
                await db.commit()


class TestNetz:
    async def test_signal_nur_ueber_mobilfunk(self, client, org):  # noqa: F811
        geraet = await _anlegen(client, org)
        kopf = h((await _einloesen(client, geraet["code"]))["token"])

        async def hallo(**daten) -> dict:
            await client.post("/api/geraete/hallo", json=daten, headers=kopf)
            return await _zeile(client, org)

        # Ohne Angabe: Mobilfunk, wie jede Firmware von vor E14.
        z = await hallo(signal_dbm=-95)
        assert (z["netz"], z["signal_dbm"]) == ("mobil", -95)
        # WLAN: kein RSRP, also kein Signal — der alte Wert bleibt stehen, die Ansicht zeigt WLAN.
        z = await hallo(netz="wlan", signal_dbm=-40)
        assert (z["netz"], z["signal_dbm"]) == ("wlan", -95)
        z = await hallo(netz="mobil", signal_dbm=-101)
        assert (z["netz"], z["signal_dbm"]) == ("mobil", -101)
        # Unbekannter Weg: verworfen, und das Signal mit ihm.
        z = await hallo(netz="satellit", signal_dbm=-70)
        assert (z["netz"], z["signal_dbm"]) == ("mobil", -101)
        await client.post("/api/geraete/positionen", json={"netz": "wlan", "fixes": []}, headers=kopf)
        assert (await _zeile(client, org))["netz"] == "wlan"
