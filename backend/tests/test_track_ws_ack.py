"""Quittungen auf dem Fahrer-Link.

Ein Fahrer, der „Angekommen" tippt, muss wissen, ob es angekommen ist. Der
Broadcast allein sagt das nicht verlässlich: Er trägt keinen Absender, schweigt
bei einer Ablehnung, und eine wiederholte Meldung würde ein zweites Mal
verarbeitet — bei einem technischen Halt also ein zweiter Alarm.

Die Tests sprechen mit ``track_ws`` über eine nachgebaute WebSocket in derselben
Event-Loop; ein ``TestClient`` liefe in einem eigenen Thread und käme dem
asyncpg-Pool in die Quere.
"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect
from sqlalchemy import delete

from app.api.routes import track as track_module
from app.database import AsyncSessionLocal, engine
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.organization import Organization, UserOrganization
from app.models.share_link import ConvoyShareLink
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services import belegung as belegung_modul
from app.services.belegung import Belegungen
from app.services.tracking import tracking_manager

# Die Kennung der App auf diesem Gerät (Query-Parameter ``client``). Dieselbe
# über Verbindungen hinweg: Ein Gerät, das nach einem Abriss wiederkommt, hält
# sein Fahrzeug weiter.
GERAET = "geraet-app-01"


@pytest.fixture(autouse=True)
async def reset_db_engine():
    """Verbindungspool vor und nach jedem Test schließen (siehe mcp_fixtures).

    Auch **vorher**: Läuft diese Datei nach einer, die nicht aufräumt, gehört
    die gepoolte Verbindung noch der Event-Loop des vorigen Tests.
    """
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def frische_belegungen(monkeypatch):
    monkeypatch.setattr(belegung_modul, "belegungen", Belegungen())


@pytest.fixture(autouse=True)
def frische_quittungen():
    tracking_manager._acks.clear()
    yield
    tracking_manager._acks.clear()


@pytest.fixture
async def verband():
    """Ein Verband mit einem Fahrzeug, einem Fahrer-Link und einem Lese-Link."""
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(email=f"ack-{marker}@test.invalid", hashed_password="x", is_active=True)
        db.add(user)
        await db.flush()
        org = Organization(name=f"Org {marker}", slug=f"org-{marker}", owner_id=user.id)
        db.add(org)
        await db.flush()
        db.add(UserOrganization(user_id=user.id, organization_id=org.id, role="planer"))
        convoy = Convoy(name=f"Verband {marker}", owner_id=user.id, organization_id=org.id)
        fahrzeug = Vehicle(name=f"LF 10 {marker}", callsign="Florian 1", owner_id=user.id)
        db.add_all([convoy, fahrzeug])
        await db.flush()
        db.add(ConvoyVehicle(convoy_id=convoy.id, vehicle_id=fahrzeug.id, position=0))
        fahrer = ConvoyShareLink(
            convoy_id=convoy.id, slug=f"f{marker}", scope="driver", created_by_id=user.id
        )
        leser = ConvoyShareLink(
            convoy_id=convoy.id, slug=f"l{marker}", scope="track", created_by_id=user.id
        )
        db.add_all([fahrer, leser])
        await db.commit()
        ids = SimpleNamespace(
            user_id=user.id,
            org_id=org.id,
            convoy_id=convoy.id,
            vehicle_id=fahrzeug.id,
            fahrer=fahrer.slug,
            leser=leser.slug,
        )

    yield ids

    async with AsyncSessionLocal() as db:
        await db.execute(delete(ConvoyShareLink).where(ConvoyShareLink.convoy_id == ids.convoy_id))
        await db.execute(delete(ConvoyVehicle).where(ConvoyVehicle.convoy_id == ids.convoy_id))
        await db.execute(delete(Convoy).where(Convoy.id == ids.convoy_id))
        await db.execute(delete(Vehicle).where(Vehicle.id == ids.vehicle_id))
        await db.execute(
            delete(UserOrganization).where(UserOrganization.organization_id == ids.org_id)
        )
        await db.execute(delete(Organization).where(Organization.id == ids.org_id))
        await db.execute(delete(User).where(User.id == ids.user_id))
        await db.commit()


@pytest.fixture
def gesendet(monkeypatch):
    """Fängt ab, was an alle geöffneten Ansichten ginge."""
    frames: list[dict] = []

    async def _broadcast(_convoy_id, payload):
        frames.append(payload)

    monkeypatch.setattr(tracking_manager, "broadcast", _broadcast)
    return frames


class FakeSocket:
    """Spielt eine Folge von Client-Frames ab und hält fest, was zurückkam."""

    def __init__(self, frames: list):
        self._frames = list(frames)
        self.sent: list[dict] = []

    async def accept(self):
        pass

    async def close(self, code: int = 1000):
        self.closed = code

    async def send_json(self, data):
        self.sent.append(data)

    async def receive_json(self):
        if not self._frames:
            raise WebSocketDisconnect()
        return self._frames.pop(0)

    def acks(self) -> list[dict]:
        return [f for f in self.sent if f.get("type") == "ack"]


async def _sprich(slug: str, frames: list, client: str | None = GERAET) -> FakeSocket:
    ws = FakeSocket(frames)
    await track_module.track_ws(slug, ws, token=None, client=client)
    return ws


def _status(ids, status="arrived", level=None, client_id="c1", **extra) -> dict:
    frame = {"type": "status", "vehicle_id": str(ids.vehicle_id), "vehicle_status": status,
             "status_level": level, **extra}
    if client_id is not None:
        frame["client_id"] = client_id
    return frame


async def test_der_server_sagt_beim_verbinden_was_er_kann(verband, gesendet):
    ws = await _sprich(verband.fahrer, [])
    assert {
        "type": "hello",
        "protocol": 2,
        "features": ["ack", "ack-betriebsstoff", "alarm-quittung"],
    } in ws.sent


async def test_ohne_geraetekennung_kein_hello(verband, gesendet):
    # Wie die Belegung: Ein Client ohne Kennung ist älter als beides und kennt
    # den Typ nicht.
    ws = await _sprich(verband.fahrer, [], client=None)
    assert ws.sent == []


async def test_ein_fremd_belegtes_fahrzeug_wird_abgelehnt_quittiert(verband, gesendet):
    await _sprich(verband.fahrer, [_status(verband, client_id="a")], client="geraet-anderes")
    ws = await _sprich(verband.fahrer, [_status(verband, client_id="b")])

    assert {"type": "belegung_abgelehnt", "vehicle_id": str(verband.vehicle_id)} in ws.sent
    assert ws.acks() == [{"type": "ack", "client_id": "b", "frame": "status",
                          "result": "rejected", "reason": "vehicle-taken"}]


async def test_status_wird_dem_absender_quittiert(verband, gesendet):
    ws = await _sprich(
        verband.fahrer, [_status(verband, "technical_halt", "dringend", status_note="Reifenschaden")]
    )

    [ack] = ws.acks()
    assert ack["client_id"] == "c1"
    assert ack["frame"] == "status"
    assert ack["result"] == "ok"
    assert ack["applied"] == {
        "vehicle_status": "technical_halt",
        "status_level": "dringend",
        "status_note": "Reifenschaden",
    }
    assert ack["ts"]
    # Die Quittung geht nur an den Absender — der Broadcast bleibt, wie er war.
    assert [f["type"] for f in gesendet] == ["status_update", "alert"]


async def test_ohne_client_id_bleibt_alles_beim_alten(verband, gesendet):
    ws = await _sprich(verband.fahrer, [_status(verband, client_id=None)])

    assert ws.acks() == []
    assert [f["type"] for f in gesendet] == ["status_update"]


@pytest.mark.parametrize(
    ("frame", "grund"),
    [
        ({"vehicle_id": "kein-uuid"}, "invalid-vehicle"),
        ({"vehicle_status": "gibts_nicht"}, "unknown-status"),
        ({"vehicle_status": "technical_halt", "status_level": "egal"}, "invalid-level"),
        ({"vehicle_id": "00000000-0000-4000-8000-000000000000"}, "vehicle-not-in-convoy"),
    ],
)
async def test_eine_ablehnung_nennt_ihren_grund(verband, gesendet, frame, grund):
    ws = await _sprich(verband.fahrer, [{**_status(verband), **frame}])

    [ack] = ws.acks()
    assert ack == {"type": "ack", "client_id": "c1", "frame": "status",
                   "result": "rejected", "reason": grund}
    assert gesendet == []


async def test_staerke_wird_quittiert(verband, gesendet):
    frame = {"type": "staerke", "client_id": "s1", "vehicle_id": str(verband.vehicle_id),
             "fuehrer": 0, "unterfuehrer": 1, "mannschaften": 7}
    ws = await _sprich(verband.fahrer, [frame])

    [ack] = ws.acks()
    assert ack["frame"] == "staerke"
    assert ack["result"] == "ok"
    assert ack["applied"] == {"fuehrer": 0, "unterfuehrer": 1, "mannschaften": 7}


async def test_unplausible_staerke_wird_abgelehnt(verband, gesendet):
    frame = {"type": "staerke", "client_id": "s1", "vehicle_id": str(verband.vehicle_id),
             "fuehrer": 0, "unterfuehrer": 1, "mannschaften": 100}
    ws = await _sprich(verband.fahrer, [frame])

    assert ws.acks()[0]["reason"] == "invalid-staerke"


async def test_lese_link_sagt_warum_nichts_geschah(verband, gesendet):
    ws = await _sprich(verband.leser, [_status(verband)])

    assert ws.acks() == [{"type": "ack", "client_id": "c1", "frame": "status",
                          "result": "rejected", "reason": "read-only"}]
    assert gesendet == []


async def test_lese_link_ohne_client_id_schweigt_wie_bisher(verband, gesendet):
    ws = await _sprich(verband.leser, [_status(verband, client_id=None)])
    assert ws.acks() == []


async def test_eine_wiederholte_meldung_loest_keinen_zweiten_alarm_aus(verband, gesendet):
    halt = _status(verband, "breakdown", "total")
    erste = await _sprich(verband.fahrer, [halt])
    # Die Verbindung riss ab, ehe die Quittung ankam — die App schickt nach.
    zweite = await _sprich(verband.fahrer, [dict(halt)])

    assert erste.acks() == zweite.acks()
    assert [f["type"] for f in gesendet] == ["status_update", "alert"]


async def test_gleichzeitige_duplikate_warten_auf_das_original(verband, gesendet):
    halt = _status(verband, "breakdown", "total")
    a, b = await asyncio.gather(
        _sprich(verband.fahrer, [halt]), _sprich(verband.fahrer, [dict(halt)])
    )

    assert a.acks() == b.acks()
    assert a.acks()[0]["result"] == "ok"
    assert [f["type"] for f in gesendet] == ["status_update", "alert"]


async def test_verschiedene_kennungen_sind_verschiedene_meldungen(verband, gesendet):
    await _sprich(verband.fahrer, [_status(verband, client_id="a"), _status(verband, client_id="b")])
    assert [f["type"] for f in gesendet] == ["status_update", "status_update"]


async def test_ein_serverfehler_kappt_die_verbindung_nicht(verband, gesendet, monkeypatch):
    aufrufe = 0
    original = track_module._ingest_driver_status

    async def _wackelt(convoy_uuid, msg):
        nonlocal aufrufe
        aufrufe += 1
        if aufrufe == 1:
            raise RuntimeError("Datenbank weg")
        return await original(convoy_uuid, msg)

    monkeypatch.setattr(track_module, "_ingest_driver_status", _wackelt)
    ws = await _sprich(verband.fahrer, [_status(verband), _status(verband)])

    # Der Fehler wird nicht gemerkt: Derselbe Frame darf es erneut versuchen.
    assert [a["result"] for a in ws.acks()] == ["rejected", "ok"]
    assert ws.acks()[0]["reason"] == "server-error"


async def test_eine_ueberlange_kennung_zaehlt_als_keine(verband, gesendet):
    ws = await _sprich(verband.fahrer, [_status(verband, client_id="x" * 65)])

    assert ws.acks() == []
    assert [f["type"] for f in gesendet] == ["status_update"]


async def test_ein_abbruch_laesst_duplikate_nicht_ewig_warten(verband, gesendet, monkeypatch):
    haengt = asyncio.Event()

    async def _haengt(convoy_uuid, msg):
        haengt.set()
        await asyncio.sleep(3600)

    wartet = asyncio.Event()
    claim = tracking_manager.claim_ack

    def _claim(key):
        known = claim(key)
        if known is not None:
            wartet.set()
        return known

    monkeypatch.setattr(track_module, "_ingest_driver_status", _haengt)
    monkeypatch.setattr(tracking_manager, "claim_ack", _claim)
    original = asyncio.create_task(_sprich(verband.fahrer, [_status(verband)]))
    await haengt.wait()
    duplikat = asyncio.create_task(_sprich(verband.fahrer, [_status(verband)]))
    # Erst abbrechen, wenn das Duplikat wirklich auf das Original wartet.
    await wartet.wait()

    original.cancel()
    zweite = await asyncio.wait_for(duplikat, timeout=2)

    assert zweite.acks()[0]["reason"] == "server-error"
    # Freigegeben: Ein späterer Versuch wird wieder verarbeitet.
    assert tracking_manager._acks == {}
