"""Positionsquelle: sendet ein Tracker, gehört ihm die Position — die Meldungen bleiben der Besatzung.

Erst die Entscheidung ohne Uhr und Netz, dann der Weg durch die App an allen
drei Telefonpfaden (REST, angemeldeter WebSocket über die Regel, Fahrer-Link am
gestellten Kanal) und am Tracker.
"""
import asyncio
import uuid

import pytest
from fastapi import WebSocketDisconnect

from app.api.routes import track as track_module
from app.database import AsyncSessionLocal
from app.models.convoy import ConvoyVehicle
from app.models.share_link import ConvoyShareLink
from app.services import positionsquelle as pq
from app.services.positionsquelle import Positionsquellen, entscheiden
from tests.aktionsseite_fixtures import client, h, reset_db_engine  # noqa: F401
from tests.test_tracker_geraete import _eingerichtet, _fix, _position, org  # noqa: F401

APP = "app-geraet-0001"


@pytest.fixture(autouse=True)
def frische_quellen(monkeypatch):
    monkeypatch.setattr(pq, "positionsquellen", Positionsquellen())


# ── Die Entscheidung ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "quelle,tracker_sendet,uebersteuert,erwartet",
    [
        ("tracker", True, False, "annehmen"),
        ("tracker", False, False, "annehmen"),
        ("telefon", False, False, "annehmen"),
        ("telefon", True, False, "tracker-hat-vorrang"),
        ("telefon", True, True, "annehmen"),
        ("telefon", False, True, "annehmen"),
        ("tracker", True, True, "uebersteuert"),
    ],
)
def test_entscheidung(quelle, tracker_sendet, uebersteuert, erwartet):
    assert entscheiden(quelle, tracker_sendet, uebersteuert) == erwartet


def test_tracker_hat_fuenf_minuten_vorrang_dann_nicht_mehr():
    uhr = [1000.0]
    q = Positionsquellen(uhr=lambda: uhr[0])
    assert not q.tracker_sendet("k", "v")
    q.tracker_gesehen("k", "v")
    uhr[0] += 299
    assert q.tracker_sendet("k", "v")
    assert not q.tracker_sendet("k", "anderes")
    uhr[0] += 2
    assert not q.tracker_sendet("k", "v")


def test_jedes_buendel_verlaengert_und_vergessen_beendet():
    uhr = [0.0]
    q = Positionsquellen(uhr=lambda: uhr[0])
    q.tracker_gesehen("k", "v")
    uhr[0] += 200
    q.tracker_gesehen("k", "v")
    uhr[0] += 200
    assert q.tracker_sendet("k", "v")
    q.vergessen("k", "v")
    assert not q.tracker_sendet("k", "v")


# ── Durch die App ────────────────────────────────────────────────────────────


def _telefon(vehicle_id, lon: float) -> dict:
    return {"vehicle_id": str(vehicle_id), "lat": 47.8, "lon": lon}


async def _rest(client, org, lon: float, vehicle_id=None) -> dict:
    r = await client.post(
        f"/api/convoys/{org.konvoi}/positions",
        json=_telefon(vehicle_id or org.hlf, lon),
        headers=h(org.fahrer),
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _uebersteuern(client, org, an: bool, token=None):
    return await client.patch(
        f"/api/convoys/{org.konvoi}/vehicles/{org.hlf}/positionsquelle",
        json={"tracker_uebersteuern": an},
        headers=h(token or org.admin),
    )


async def test_tracker_vor_telefon_beim_selben_fahrzeug(client, org):
    _, kopf = await _eingerichtet(client, org)
    await client.post("/api/geraete/positionen", json={"fixes": [_fix(5, 11.10)]}, headers=kopf)
    assert await _rest(client, org, 11.90) == {"status": "tracker"}
    pos = await _position(org.konvoi, org.hlf)
    assert (pos.lon, pos.quelle) == (11.10, "tracker")
    liste = (await client.get(f"/api/convoys/{org.konvoi}/positions", headers=h(org.admin))).json()
    assert liste[0]["quelle"] == "tracker"


async def test_ein_anderes_fahrzeug_bleibt_dem_telefon(client, org):
    _, kopf = await _eingerichtet(client, org)
    await client.post("/api/geraete/positionen", json={"fixes": [_fix(5, 11.10)]}, headers=kopf)
    assert await _rest(client, org, 11.90, vehicle_id=org.mtw) == {"status": "ok"}
    pos = await _position(org.konvoi, org.mtw)
    assert (pos.lon, pos.quelle) == (11.90, None)


async def test_ohne_tracker_gilt_das_telefon_wie_bisher(client, org):
    assert await _rest(client, org, 11.90) == {"status": "ok"}
    assert (await _position(org.konvoi, org.hlf)).quelle is None


async def test_verstummter_tracker_gibt_die_position_frei(client, org, monkeypatch):
    uhr = [0.0]
    monkeypatch.setattr(pq, "positionsquellen", Positionsquellen(uhr=lambda: uhr[0]))
    _, kopf = await _eingerichtet(client, org)
    await client.post("/api/geraete/positionen", json={"fixes": [_fix(5, 11.10)]}, headers=kopf)
    uhr[0] += 299
    assert await _rest(client, org, 11.90) == {"status": "tracker"}
    uhr[0] += 2
    assert await _rest(client, org, 11.95) == {"status": "ok"}
    pos = await _position(org.konvoi, org.hlf)
    assert (pos.lon, pos.quelle) == (11.95, None)


async def test_die_fuehrung_uebersteuert_und_nimmt_es_zurueck(client, org):
    _, kopf = await _eingerichtet(client, org)
    await client.post("/api/geraete/positionen", json={"fixes": [_fix(5, 11.10)]}, headers=kopf)

    # Fahrer dürfen nicht übersteuern — das ist eine Entscheidung der Führung.
    assert (await _uebersteuern(client, org, True, org.fahrer)).status_code == 403
    r = await _uebersteuern(client, org, True)
    assert r.status_code == 200 and r.json()["tracker_uebersteuert_at"] is not None

    # Sofort, nicht erst nach fünf Minuten.
    assert await _rest(client, org, 11.90) == {"status": "ok"}
    # Der Tracker wird zwar angenommen (er soll nicht in den Zustand „gesperrt"),
    # aber in diesen Konvoi schreibt er nichts mehr.
    r = await client.post("/api/geraete/positionen", json={"fixes": [_fix(1, 11.20)]}, headers=kopf)
    assert r.json()["angenommen"] == 1
    pos = await _position(org.konvoi, org.hlf)
    assert (pos.lon, pos.quelle) == (11.90, None)
    konvoi = (await client.get(f"/api/convoys/{org.konvoi}", headers=h(org.admin))).json()
    cv = next(c for c in konvoi["convoy_vehicles"] if c["vehicle"]["id"] == str(org.hlf))
    assert cv["tracker_uebersteuert_at"] is not None and cv["tracker_uebersteuert_von"]

    r = await _uebersteuern(client, org, False)
    assert r.status_code == 200
    # Jünger als die Telefonposition von eben: die Fixzeit ist sekundengenau,
    # die Serverzeit nicht — eine Sekunde Zukunft liegt in der Toleranz.
    await client.post("/api/geraete/positionen", json={"fixes": [_fix(-2, 11.30)]}, headers=kopf)
    assert await _rest(client, org, 11.99) == {"status": "tracker"}
    assert (await _position(org.konvoi, org.hlf)).lon == 11.30


async def test_gps_freigabe_zuruecksetzen_laesst_den_tracker_von_vorn_anfangen(client, org):
    _, kopf = await _eingerichtet(client, org)
    await client.post("/api/geraete/positionen", json={"fixes": [_fix(5, 11.10)]}, headers=kopf)
    r = await client.delete(f"/api/convoys/{org.konvoi}/vehicles/{org.hlf}/position", headers=h(org.admin))
    assert r.status_code == 200
    assert not pq.positionsquellen.tracker_sendet(str(org.konvoi), str(org.hlf))


# ── Fahrer-Link am gestellten Kanal ──────────────────────────────────────────


class GestellteVerbindung:
    def __init__(self, frames: list[dict]):
        self._frames = list(frames)
        self._getrennt = asyncio.Event()
        self.empfangen: list[dict] = []

    async def accept(self):
        pass

    async def close(self, code: int = 1000):
        pass

    async def send_json(self, data):
        self.empfangen.append(data)

    async def receive_json(self):
        if self._frames:
            return self._frames.pop(0)
        await self._getrennt.wait()
        raise WebSocketDisconnect()

    def trennen(self):
        self._getrennt.set()


async def _fahrer_link(org) -> str:
    async with AsyncSessionLocal() as db:
        link = ConvoyShareLink(
            convoy_id=org.konvoi, slug=f"q{uuid.uuid4().hex[:7]}", scope="driver", created_by_id=org.users[0]
        )
        db.add(link)
        await db.commit()
        return link.slug


async def _verbinden(slug: str, frames: list[dict], client_kennung: str | None):
    ws = GestellteVerbindung(frames)
    task = asyncio.create_task(track_module.track_ws(slug, ws, token=None, client=client_kennung))
    for _ in range(200):
        await asyncio.sleep(0.01)
        if not ws._frames:
            break
    await asyncio.sleep(0.2)
    return ws, task


async def test_am_fahrer_link_erfaehrt_nur_der_absender_davon(client, org):
    _, kopf = await _eingerichtet(client, org)
    await client.post("/api/geraete/positionen", json={"fixes": [_fix(5, 11.10)]}, headers=kopf)
    slug = await _fahrer_link(org)
    try:
        app, task = await _verbinden(slug, [{"type": "belegen", "vehicle_id": str(org.hlf)}, _telefon(org.hlf, 11.90)], APP)
        alt, alt_task = await _verbinden(slug, [_telefon(org.mtw, 11.80)], None)
        assert {"type": "position_abgelehnt", "vehicle_id": str(org.hlf), "grund": "tracker"} in app.empfangen
        # Belegt hat die App das Fahrzeug trotzdem: die Meldungen bleiben ihr.
        assert {"type": "belegung", "vehicle_id": str(org.hlf), "belegt": True} in app.empfangen
        assert all(m.get("type") != "position_abgelehnt" for m in alt.empfangen)
        assert (await _position(org.konvoi, org.hlf)).lon == 11.10
        assert (await _position(org.konvoi, org.mtw)).lon == 11.80
        for ws, t in ((app, task), (alt, alt_task)):
            ws.trennen()
            await asyncio.wait_for(t, timeout=5)
    finally:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import delete

            await db.execute(delete(ConvoyShareLink).where(ConvoyShareLink.convoy_id == org.konvoi))
            await db.commit()


async def test_status_der_besatzung_geht_weiter_durch(client, org):
    """Das ist der Sinn der Aufteilung: der Tracker nimmt der App nur die Position."""
    _, kopf = await _eingerichtet(client, org)
    await client.post("/api/geraete/positionen", json={"fixes": [_fix(5, 11.10)]}, headers=kopf)
    r = await client.patch(
        f"/api/convoys/{org.konvoi}/vehicles/{org.hlf}/status",
        json={"vehicle_status": "technical_halt", "status_level": "standard", "status_note": "Reifen"},
        headers=h(org.fahrer),
    )
    assert r.status_code == 200, r.text
    async with AsyncSessionLocal() as db:
        cv = await db.get(ConvoyVehicle, (org.konvoi, org.hlf))
        assert cv.vehicle_status == "technical_halt"
