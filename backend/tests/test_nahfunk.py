"""Nahfunk: Die Begleit-App meldet über den Tracker im Fahrzeug (E15 im Tracker-Plan).

Was hier zugesagt wird:

- Tracker und App bekommen **denselben** Zugang: der Tracker mit der Anweisung, die App
  über den Fahrer-Link, und zwar nur die Verbindung, die das Fahrzeug belegt. Ohne
  laufenden Konvoi, ohne Lizenz oder ohne Tracker gibt es keinen.
- Der Zugang wechselt, wenn ein anderes Gerät das Fahrzeug belegt oder es freigegeben
  wird — **nicht**, wenn die Belegung im Funkloch abläuft. Sonst endete der Weg über den
  Tracker nach fünf Minuten, genau dann, wenn er gebraucht wird.
- ``meldungen`` wendet Status, Stärke und Betriebsstoff an wie der Fahrer-Link, mit
  derselben Quittung: Eine ``client_id`` zählt über beide Wege nur einmal, ein zweiter
  technischer Halt wäre ein zweiter Alarm.
- Eine Meldung, die länger als 30 min unterwegs war, wird abgelehnt — außer der Kanal
  hatte sie schon, dann gilt die erste Antwort.
"""
import base64
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.api.routes import track as track_module
from app.database import AsyncSessionLocal
from app.models.convoy import ConvoyVehicle
from app.models.share_link import ConvoyShareLink
from app.services import belegung as belegung_modul
from app.services import nahfunk
from app.services.belegung import Belegungen
from app.services.tracking import tracking_manager
from tests.aktionsseite_fixtures import client, reset_db_engine  # noqa: F401
from tests.test_track_ws_ack import FakeSocket
from tests.test_tracker_geraete import (  # noqa: F401
    _anlegen,
    _eingerichtet,
    _konvoi_status,
    ohne_lizenz,
    org,
)

APP = "geraet-app-01"
ANDERE_APP = "geraet-app-02"


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Regeln ohne Datenbank ──────────────────────────────────────────────────


class TestZugang:
    def test_form(self):
        z = nahfunk.zugang("geheim", "g1", "v1", ["k1"], ["app"])
        assert len(z["kennung"]) == 8 and int(z["kennung"], 16) >= 0
        assert len(base64.b64decode(z["schluessel"], validate=True)) == 32
        assert z["gueltig_bis"] is None

    def test_gleich_fuer_gleiche_zutaten_unabhaengig_von_der_reihenfolge(self):
        a = nahfunk.zugang("geheim", "g1", "v1", ["k1", "k2"], ["b", "a"])
        b = nahfunk.zugang("geheim", "g1", "v1", ["k2", "k1"], ["a", "b", "a"])
        assert a == b

    @pytest.mark.parametrize(
        "anders",
        [
            {"instanz_geheimnis": "anderes"},
            {"geraet_id": "g2"},
            {"fahrzeug_id": "v2"},
            {"konvois": ["k1", "k3"]},
            {"halter": ["andere-app"]},
            {"halter": []},
        ],
    )
    def test_jede_zutat_wechselt_den_schluessel(self, anders):
        basis = {"instanz_geheimnis": "geheim", "geraet_id": "g1", "fahrzeug_id": "v1",
                 "konvois": ["k1"], "halter": ["app"]}
        a = nahfunk.zugang(**basis)
        b = nahfunk.zugang(**{**basis, **anders})
        assert a["schluessel"] != b["schluessel"] and a["kennung"] != b["kennung"]

    def test_ws_nachricht(self):
        assert nahfunk.ws_nachricht("v1", None) == {"type": "nahfunk", "vehicle_id": "v1", "kennung": None}
        z = nahfunk.zugang("geheim", "g1", "v1", ["k1"], ["app"])
        assert nahfunk.ws_nachricht("v1", z) == {"type": "nahfunk", "vehicle_id": "v1", **z}


class TestMeldungenLesen:
    def test_zu_viele_oder_keine_liste_ist_eine_400(self):
        with pytest.raises(ValueError):
            nahfunk.meldungen_lesen([{"client_id": f"c{i}"} for i in range(17)])
        with pytest.raises(ValueError):
            nahfunk.meldungen_lesen({"client_id": "c1"})

    def test_ohne_client_id_kein_ergebnis_unbekannte_art_bleibt_zum_ablehnen(self):
        liste = nahfunk.meldungen_lesen([
            {"frame": {"type": "status"}},
            {"client_id": "x" * 65, "frame": {"type": "status"}},
            {"client_id": "c1", "frame": {"type": "position", "lat": 1}},
            {"client_id": "c2", "frame": {"type": "staerke", "fuehrer": 1}, "erhalten": "2026-10-12T08:00:00Z"},
        ])
        assert [(m.client_id, m.art) for m in liste] == [("c1", None), ("c2", "staerke")]
        assert liste[1].erhalten == datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)

    def test_veraltet(self):
        jetzt = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
        [frisch, alt, ohne] = nahfunk.meldungen_lesen([
            {"client_id": "a", "frame": {}, "erhalten": _iso(jetzt - timedelta(minutes=30))},
            {"client_id": "b", "frame": {}, "erhalten": _iso(jetzt - timedelta(minutes=31))},
            {"client_id": "c", "frame": {}},
        ])
        assert not nahfunk.veraltet(frisch, jetzt)
        assert nahfunk.veraltet(alt, jetzt)
        assert not nahfunk.veraltet(ohne, jetzt)

    def test_ergebnis_aus_quittung_und_mehrere_konvois(self):
        ok = nahfunk.ergebnis_aus_quittung("c1", {"result": "ok", "applied": {"vehicle_status": "arrived"}})
        nein = nahfunk.ergebnis_aus_quittung("c1", {"result": "rejected", "reason": "invalid-level"})
        assert ok == {"client_id": "c1", "ergebnis": "ok", "applied": {"vehicle_status": "arrived"}}
        assert nein == {"client_id": "c1", "ergebnis": "abgelehnt", "grund": "invalid-level"}
        assert nahfunk.zusammenfassen("c1", [nein, ok]) == ok
        assert nahfunk.zusammenfassen("c1", [nein]) == nein


class TestLetzterHalter:
    def test_ueberdauert_den_ablauf_wechselt_mit_dem_naechsten_geraet(self):
        uhr = [0.0]
        b = Belegungen(uhr=lambda: uhr[0], ablauf_s=300)
        b.beanspruchen("k", "v", APP)
        uhr[0] = 1000.0
        assert b.belegte("k") == []  # die Belegung ist abgelaufen …
        assert b.letzter_halter("k", "v") == APP  # … der Weg über den Tracker nicht
        b.beanspruchen("k", "v", ANDERE_APP)
        assert b.letzter_halter("k", "v") == ANDERE_APP

    def test_freigeben_beendet_ihn_auch_nach_dem_ablauf(self):
        uhr = [0.0]
        b = Belegungen(uhr=lambda: uhr[0], ablauf_s=300)
        b.beanspruchen("k", "v", APP)
        b.freigeben("k", "v", APP)
        assert b.letzter_halter("k", "v") is None
        b.beanspruchen("k", "v", APP)
        uhr[0] = 1000.0
        b.freigeben("k", "v", ANDERE_APP)  # ein fremdes Gerät kann nichts beenden
        assert b.letzter_halter("k", "v") == APP
        b.freigeben("k", "v", None)  # die Führung schon
        assert b.letzter_halter("k", "v") is None


# ── Durch die App ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def frische_belegungen(monkeypatch):
    monkeypatch.setattr(belegung_modul, "belegungen", Belegungen())


@pytest.fixture(autouse=True)
def frische_quittungen():
    tracking_manager._acks.clear()
    yield
    tracking_manager._acks.clear()


@pytest.fixture
def gesendet(monkeypatch):
    frames: list[tuple[str, dict]] = []

    async def _broadcast(convoy_id, payload):
        frames.append((convoy_id, payload))

    monkeypatch.setattr(tracking_manager, "broadcast", _broadcast)
    return frames


@pytest.fixture
async def fahrer_link(org):
    slug = f"nf{uuid.uuid4().hex[:10]}"
    async with AsyncSessionLocal() as db:
        db.add(ConvoyShareLink(convoy_id=org.konvoi, slug=slug, scope="driver", created_by_id=org.users[0]))
        await db.commit()
    yield slug
    async with AsyncSessionLocal() as db:
        await db.execute(delete(ConvoyShareLink).where(ConvoyShareLink.slug == slug))
        await db.commit()


async def _belegen(slug: str, vehicle_id, client: str = APP) -> list[dict]:
    """Die App wählt ihr Fahrzeug; gibt zurück, was sie über den Kanal bekam."""
    ws = FakeSocket([{"type": "belegen", "vehicle_id": str(vehicle_id)}])
    await track_module.track_ws(slug, ws, token=None, client=client)
    return [f for f in ws.sent if f.get("type") == "nahfunk"]


def _halt(client_id: str = "c1", **extra) -> dict:
    return {
        "client_id": client_id,
        "frame": {"type": "status", "vehicle_status": "technical_halt", "status_level": "dringend",
                  "status_note": "Reifen"},
        **extra,
    }


async def _status(convoy_id, vehicle_id) -> tuple[str | None, str | None]:
    async with AsyncSessionLocal() as db:
        cv = (await db.execute(
            select(ConvoyVehicle).where(ConvoyVehicle.convoy_id == convoy_id, ConvoyVehicle.vehicle_id == vehicle_id)
        )).scalar_one()
        return cv.vehicle_status, cv.status_level


class TestZugangDurchDieApp:
    async def test_tracker_und_app_bekommen_denselben(self, client, org, fahrer_link):
        _, kopf = await _eingerichtet(client, org)
        [frame] = await _belegen(fahrer_link, org.hlf)
        anweisung = (await client.post("/api/geraete/hallo", json={}, headers=kopf)).json()
        assert anweisung["modus"] == "senden"
        assert frame["kennung"] == anweisung["nahfunk"]["kennung"]
        assert frame["schluessel"] == anweisung["nahfunk"]["schluessel"]
        assert frame["vehicle_id"] == str(org.hlf)

    async def test_hello_nennt_nahfunk(self, client, org, fahrer_link):
        ws = FakeSocket([])
        await track_module.track_ws(fahrer_link, ws, token=None, client=APP)
        hello = next(f for f in ws.sent if f.get("type") == "hello")
        assert "nahfunk" in hello["features"]

    async def test_ohne_tracker_zieht_die_app_keinen(self, client, org, fahrer_link):
        [frame] = await _belegen(fahrer_link, org.mtw)
        assert frame == {"type": "nahfunk", "vehicle_id": str(org.mtw), "kennung": None}

    async def test_ohne_laufenden_konvoi_keiner(self, client, org, fahrer_link):
        _, kopf = await _eingerichtet(client, org)
        await _konvoi_status(org.konvoi, "planning")
        anweisung = (await client.post("/api/geraete/hallo", json={}, headers=kopf)).json()
        assert anweisung["modus"] == "schweigen" and anweisung["nahfunk"] is None
        [frame] = await _belegen(fahrer_link, org.hlf)
        assert frame["kennung"] is None

    async def test_ohne_lizenz_keiner(self, client, org, fahrer_link, ohne_lizenz):
        _, kopf = await _eingerichtet_mit_lizenz(client, org)
        anweisung = (await client.post("/api/geraete/hallo", json={}, headers=kopf)).json()
        assert anweisung["nahfunk"] is None

    async def test_andere_besatzung_anderer_schluessel_funkloch_nicht(self, client, org, fahrer_link, monkeypatch):
        uhr = [0.0]
        monkeypatch.setattr(belegung_modul, "belegungen", Belegungen(uhr=lambda: uhr[0]))
        _, kopf = await _eingerichtet(client, org)
        [erst] = await _belegen(fahrer_link, org.hlf)
        uhr[0] = 3600.0  # eine Stunde ohne Frame der App: Belegung abgelaufen
        nach_funkloch = (await client.post("/api/geraete/hallo", json={}, headers=kopf)).json()["nahfunk"]
        assert nach_funkloch["kennung"] == erst["kennung"]
        [andere] = await _belegen(fahrer_link, org.hlf, client=ANDERE_APP)
        assert andere["kennung"] != erst["kennung"]
        jetzt = (await client.post("/api/geraete/hallo", json={}, headers=kopf)).json()["nahfunk"]
        assert jetzt["kennung"] == andere["kennung"]


async def _eingerichtet_mit_lizenz(client, org):
    """Einlösen braucht eine Lizenz; danach entzieht der Test sie wieder."""
    import app.middleware.license_guard as lgm

    alt = lgm._license_valid
    lgm._license_valid = True
    try:
        return await _eingerichtet(client, org)
    finally:
        lgm._license_valid = alt


class TestMeldungen:
    async def test_status_wird_angewendet_und_verteilt(self, client, org, gesendet):
        _, kopf = await _eingerichtet(client, org)
        r = await client.post("/api/geraete/meldungen", json={"meldungen": [_halt()]}, headers=kopf)
        assert r.status_code == 200, r.text
        antwort = r.json()
        assert antwort["modus"] == "senden" and antwort["nahfunk"] is not None
        assert antwort["ergebnisse"] == [{
            "client_id": "c1", "ergebnis": "ok",
            "applied": {"vehicle_status": "technical_halt", "status_level": "dringend", "status_note": "Reifen"},
        }]
        assert await _status(org.konvoi, org.hlf) == ("technical_halt", "dringend")
        arten = [p["type"] for _, p in gesendet]
        assert arten == ["status_update", "alert"]

    async def test_dieselbe_client_id_zaehlt_einmal_auch_ueber_den_kanal(self, client, org, gesendet, fahrer_link):
        _, kopf = await _eingerichtet(client, org)
        # Erst über den Kanal …
        ws = FakeSocket([{"type": "status", "vehicle_id": str(org.hlf), "vehicle_status": "arrived",
                          "client_id": "c1"}])
        await track_module.track_ws(fahrer_link, ws, token=None, client=APP)
        vorher = len(gesendet)
        # … dann dieselbe Meldung über den Tracker, mit anderem Inhalt: es gilt die erste.
        r = await client.post("/api/geraete/meldungen", json={"meldungen": [_halt("c1")]}, headers=kopf)
        assert r.json()["ergebnisse"][0]["applied"]["vehicle_status"] == "arrived"
        assert len(gesendet) == vorher
        assert await _status(org.konvoi, org.hlf) == ("arrived", None)

    async def test_veraltet_ausser_der_kanal_hatte_sie_schon(self, client, org, gesendet):
        _, kopf = await _eingerichtet(client, org)
        alt = _iso(datetime.now(timezone.utc) - timedelta(minutes=45))
        r = await client.post(
            "/api/geraete/meldungen", json={"meldungen": [_halt("c1", erhalten=alt)]}, headers=kopf
        )
        assert r.json()["ergebnisse"] == [{"client_id": "c1", "ergebnis": "abgelehnt", "grund": "veraltet"}]
        assert gesendet == []
        frisch = await client.post("/api/geraete/meldungen", json={"meldungen": [_halt("c2")]}, headers=kopf)
        assert frisch.json()["ergebnisse"][0]["ergebnis"] == "ok"
        nochmal = await client.post(
            "/api/geraete/meldungen", json={"meldungen": [_halt("c2", erhalten=alt)]}, headers=kopf
        )
        assert nochmal.json()["ergebnisse"][0]["ergebnis"] == "ok"

    async def test_ablehnungen_tragen_ihren_grund(self, client, org, gesendet):
        _, kopf = await _eingerichtet(client, org)
        r = await client.post("/api/geraete/meldungen", json={"meldungen": [
            {"client_id": "a", "frame": {"type": "status", "vehicle_status": "breakdown", "status_level": "falsch"}},
            {"client_id": "b", "frame": {"type": "position", "lat": 1, "lon": 2}},
            {"client_id": "c", "frame": {"type": "staerke"}},
            {"frame": {"type": "status", "vehicle_status": "arrived"}},
        ]}, headers=kopf)
        assert [(e["client_id"], e["grund"]) for e in r.json()["ergebnisse"]] == [
            ("a", "invalid-level"), ("b", "ungueltig"), ("c", "invalid-staerke"),
        ]
        assert gesendet == []

    async def test_staerke_und_betriebsstoff(self, client, org, gesendet):
        _, kopf = await _eingerichtet(client, org)
        r = await client.post("/api/geraete/meldungen", json={"meldungen": [
            {"client_id": "s", "frame": {"type": "staerke", "fuehrer": 1, "mannschaften": 5}},
            {"client_id": "b", "frame": {"type": "betriebsstoff", "verbrauch": 28.5, "tank": 200, "fuellstand": 40}},
        ]}, headers=kopf)
        [s, b] = r.json()["ergebnisse"]
        assert s["applied"] == {"fuehrer": 1, "unterfuehrer": 0, "mannschaften": 5}
        assert b["applied"] == {"verbrauch": 28.5, "tank": 200, "fuellstand": 40}

    async def test_ohne_laufenden_konvoi_kein_konvoi(self, client, org, gesendet):
        _, kopf = await _eingerichtet(client, org)
        await _konvoi_status(org.konvoi, "completed")
        r = await client.post("/api/geraete/meldungen", json={"meldungen": [_halt()]}, headers=kopf)
        assert r.json()["ergebnisse"] == [{"client_id": "c1", "ergebnis": "abgelehnt", "grund": "kein-konvoi"}]
        assert r.json()["modus"] == "schweigen"
        assert gesendet == []

    async def test_ohne_lizenz_kein_402_sondern_kein_konvoi(self, client, org, gesendet, ohne_lizenz):
        _, kopf = await _eingerichtet_mit_lizenz(client, org)
        r = await client.post("/api/geraete/meldungen", json={"meldungen": [_halt()]}, headers=kopf)
        assert r.status_code == 200
        assert r.json()["ergebnisse"][0]["grund"] == "kein-konvoi"

    async def test_zwei_laufende_konvois_bekommen_beide_den_status(self, client, org, gesendet):
        await _konvoi_status(org.zweiter, "active")
        _, kopf = await _eingerichtet(client, org)
        r = await client.post("/api/geraete/meldungen", json={"meldungen": [_halt()]}, headers=kopf)
        assert r.json()["ergebnisse"][0]["ergebnis"] == "ok"
        assert await _status(org.konvoi, org.hlf) == ("technical_halt", "dringend")
        assert await _status(org.zweiter, org.hlf) == ("technical_halt", "dringend")

    async def test_zu_viele_ist_eine_400(self, client, org):
        _, kopf = await _eingerichtet(client, org)
        r = await client.post(
            "/api/geraete/meldungen", json={"meldungen": [_halt(f"c{i}") for i in range(17)]}, headers=kopf
        )
        assert r.status_code == 400

    async def test_ohne_token_401(self, client, org):
        r = await client.post("/api/geraete/meldungen", json={"meldungen": [_halt()]})
        assert r.status_code == 401

    async def test_meldung_haelt_die_belegung_der_besatzung(self, client, org, fahrer_link, gesendet, monkeypatch):
        uhr = [0.0]
        monkeypatch.setattr(belegung_modul, "belegungen", Belegungen(uhr=lambda: uhr[0]))
        _, kopf = await _eingerichtet(client, org)
        await _belegen(fahrer_link, org.hlf)
        uhr[0] = 250.0
        await client.post("/api/geraete/meldungen", json={"meldungen": [_halt()]}, headers=kopf)
        uhr[0] = 500.0  # ohne die Meldung wäre die Belegung jetzt abgelaufen
        assert belegung_modul.belegungen.belegte(str(org.konvoi)) == [str(org.hlf)]

    async def test_erwartung_des_naechsten_buendels_bleibt(self, client, org):
        """Eine Meldung ist kein Bündel: Bleiben die Positionen aus, soll es auffallen."""
        geraet, kopf = await _eingerichtet(client, org)
        await client.post("/api/geraete/positionen", json={"fixes": []}, headers=kopf)
        from app.models.ortungsgeraet import Ortungsgeraet

        async with AsyncSessionLocal() as db:
            vorher = (await db.get(Ortungsgeraet, uuid.UUID(geraet["id"]))).unterbrochen_ab
        assert vorher is not None
        await client.post("/api/geraete/meldungen", json={"meldungen": [_halt()]}, headers=kopf)
        async with AsyncSessionLocal() as db:
            nachher = (await db.get(Ortungsgeraet, uuid.UUID(geraet["id"]))).unterbrochen_ab
        assert nachher == vorher
