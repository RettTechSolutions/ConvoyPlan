"""Die Führung quittiert einen Alarm — am Server, für alle sichtbar.

Bisher quittierte jedes Gerät für sich: die Weboberfläche im eigenen Browser,
die Begleit-App auf dem eigenen Telefon. Die Besatzung im liegengebliebenen
Fahrzeug erfuhr nie, ob jemand ihren Ausfall gesehen hatte.

Die Tests sprechen wie ``test_track_ws_ack.py`` über eine nachgebaute WebSocket
in derselben Event-Loop mit ``track_ws`` und ``tracking_ws``.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect
from sqlalchemy import delete

from app.api.routes import track as track_module
from app.api.routes import tracking as tracking_module
from app.database import AsyncSessionLocal, engine
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.organization import Organization, UserOrganization
from app.models.share_link import ConvoyShareLink
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services import belegung as belegung_modul
from app.services.belegung import Belegungen
from app.services.tracking import tracking_manager

FUEHRUNG = "geraet-fuehrung-01"
BESATZUNG = "geraet-besatzung-01"


@pytest.fixture(autouse=True)
async def reset_db_engine():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def frische_belegungen(monkeypatch):
    monkeypatch.setattr(belegung_modul, "belegungen", Belegungen())


@pytest.fixture
async def verband():
    """Zwei Fahrzeuge — ELW (Führung) und LF (liegt gleich liegen) —, zwei Links."""
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"quitt-{marker}@test.invalid", hashed_password="x", is_active=True,
            first_name="Anna", last_name="Zugführer",
        )
        db.add(user)
        await db.flush()
        org = Organization(name=f"Org {marker}", slug=f"org-{marker}", owner_id=user.id)
        db.add(org)
        await db.flush()
        db.add(UserOrganization(user_id=user.id, organization_id=org.id, role="planer"))
        convoy = Convoy(name=f"Verband {marker}", owner_id=user.id, organization_id=org.id)
        elw = Vehicle(name=f"ELW {marker}", callsign="Florian 1/11", owner_id=user.id)
        lf = Vehicle(name=f"LF {marker}", callsign="Florian 1/44", owner_id=user.id)
        db.add_all([convoy, elw, lf])
        await db.flush()
        db.add_all([
            ConvoyVehicle(convoy_id=convoy.id, vehicle_id=elw.id, position=0),
            ConvoyVehicle(convoy_id=convoy.id, vehicle_id=lf.id, position=1),
        ])
        fahrer = ConvoyShareLink(
            convoy_id=convoy.id, slug=f"q{marker}", scope="driver", created_by_id=user.id
        )
        leser = ConvoyShareLink(
            convoy_id=convoy.id, slug=f"r{marker}", scope="track", created_by_id=user.id
        )
        db.add_all([fahrer, leser])
        await db.commit()
        ids = SimpleNamespace(
            user_id=user.id, org_id=org.id, convoy_id=convoy.id,
            elw=elw.id, lf=lf.id, fahrer=fahrer.slug, leser=leser.slug,
        )

    yield ids

    async with AsyncSessionLocal() as db:
        await db.execute(delete(ConvoyShareLink).where(ConvoyShareLink.convoy_id == ids.convoy_id))
        await db.execute(delete(ConvoyVehicle).where(ConvoyVehicle.convoy_id == ids.convoy_id))
        await db.execute(delete(Convoy).where(Convoy.id == ids.convoy_id))
        await db.execute(delete(Vehicle).where(Vehicle.id.in_([ids.elw, ids.lf])))
        await db.execute(
            delete(UserOrganization).where(UserOrganization.organization_id == ids.org_id)
        )
        await db.execute(delete(Organization).where(Organization.id == ids.org_id))
        await db.execute(delete(User).where(User.id == ids.user_id))
        await db.commit()


@pytest.fixture
def gesendet(monkeypatch):
    """Was an alle ginge — getrennt nach altem und neuem Verteiler."""
    frames: list[dict] = []

    async def _alle(_convoy_id, payload):
        frames.append(payload)

    async def _neu(_convoy_id, payload):
        frames.append({**payload, "_nur_mit_kennung": True})

    monkeypatch.setattr(tracking_manager, "broadcast", _alle)
    monkeypatch.setattr(tracking_manager, "broadcast_neu", _neu)
    return frames


class FakeSocket:
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


async def _sprich(slug: str, frames: list, client: str | None) -> FakeSocket:
    ws = FakeSocket(frames)
    await track_module.track_ws(slug, ws, token=None, client=client)
    return ws


async def _ausfall(ids) -> str:
    """Die Besatzung des LF meldet Totalausfall und belegt damit ihr Fahrzeug."""
    await _sprich(ids.fahrer, [{
        "type": "status", "vehicle_id": str(ids.lf), "vehicle_status": "breakdown",
        "status_level": "total",
    }], client=BESATZUNG)
    async with AsyncSessionLocal() as db:
        cv = await db.get(ConvoyVehicle, (ids.convoy_id, ids.lf))
        return cv.status_changed_at.isoformat()


def _quittieren(ids, ts: str, client_id: str | None = "q1") -> dict:
    frame = {"type": "alarm_quittieren", "vehicle_id": str(ids.lf), "alarm_ts": ts}
    if client_id is not None:
        frame["client_id"] = client_id
    return frame


def _belegen(ids) -> dict:
    return {"type": "belegen", "vehicle_id": str(ids.elw)}


async def test_die_fuehrung_quittiert_und_alle_erfahren_es(verband, gesendet):
    ts = await _ausfall(verband)
    ws = await _sprich(verband.fahrer, [_belegen(verband), _quittieren(verband, ts)], FUEHRUNG)

    [ack] = ws.acks()
    assert ack["frame"] == "alarm_quittieren"
    assert ack["result"] == "ok"
    assert ack["applied"]["quittiert_von"] == "Florian 1/11"

    [meldung] = [f for f in gesendet if f["type"] == "alarm_quittiert"]
    assert meldung["vehicle_id"] == str(verband.lf)
    assert meldung["alarm_ts"] == ts
    assert meldung["quittiert_von"] == "Florian 1/11"
    # Nur an Clients mit Gerätekennung — die ältere Weboberfläche läse den Typ
    # sonst als Position.
    assert meldung["_nur_mit_kennung"] is True


async def test_die_quittung_steht_in_der_nutzlast(verband, gesendet):
    ts = await _ausfall(verband)
    await _sprich(verband.fahrer, [_belegen(verband), _quittieren(verband, ts)], FUEHRUNG)

    async with AsyncSessionLocal() as db:
        payload = await track_module._build_payload(verband.convoy_id, db)
    lf = next(v for v in payload.vehicles if v.id == verband.lf)
    assert lf.alarm_ts.isoformat() == ts
    assert lf.alarm_quittiert_von == "Florian 1/11"
    assert lf.alarm_quittiert_at is not None
    elw = next(v for v in payload.vehicles if v.id == verband.elw)
    assert elw.alarm_ts is None


async def test_den_eigenen_alarm_quittiert_man_nicht(verband, gesendet):
    ts = await _ausfall(verband)
    ws = await _sprich(verband.fahrer, [_quittieren(verband, ts)], BESATZUNG)

    assert ws.acks()[0]["reason"] == "own-alert"
    assert not [f for f in gesendet if f["type"] == "alarm_quittiert"]


async def test_die_quittung_belegt_das_alarmierende_fahrzeug_nicht(verband, gesendet):
    ts = await _ausfall(verband)
    # Die Belegung der Besatzung ablaufen lassen: Sonst würde ein Übergriff hier
    # ohnehin abgewiesen, und der Test sähe ihn nicht.
    belegung_modul.belegungen.freigeben(str(verband.convoy_id), str(verband.lf), None)
    await _sprich(verband.fahrer, [_quittieren(verband, ts)], FUEHRUNG)

    assert belegung_modul.belegungen.gehalten(str(verband.convoy_id), FUEHRUNG) == []


async def test_ein_geraet_ohne_fahrzeug_quittiert_als_fahrer_link(verband, gesendet):
    ts = await _ausfall(verband)
    ws = await _sprich(verband.fahrer, [_quittieren(verband, ts)], FUEHRUNG)

    assert ws.acks()[0]["applied"]["quittiert_von"] == "Fahrer-Link"


async def test_die_erste_quittung_zaehlt(verband, gesendet):
    ts = await _ausfall(verband)
    await _sprich(verband.fahrer, [_belegen(verband), _quittieren(verband, ts)], FUEHRUNG)
    zweite = await _sprich(verband.fahrer, [_quittieren(verband, ts, "q2")], "geraet-zweite-01")

    assert zweite.acks()[0]["result"] == "ok"
    assert zweite.acks()[0]["applied"]["quittiert_von"] == "Florian 1/11"
    assert len([f for f in gesendet if f["type"] == "alarm_quittiert"]) == 1


async def test_ein_veralteter_alarm_wird_nicht_quittiert(verband, gesendet):
    ts = await _ausfall(verband)
    # Die Besatzung fährt wieder — der Alarm ist vorbei.
    await _sprich(verband.fahrer, [{
        "type": "status", "vehicle_id": str(verband.lf), "vehicle_status": "en_route",
    }], client=BESATZUNG)
    ws = await _sprich(verband.fahrer, [_quittieren(verband, ts)], FUEHRUNG)

    assert ws.acks()[0]["reason"] == "alarm-outdated"


async def test_ein_neuer_alarm_beginnt_ohne_quittung(verband, gesendet):
    ts = await _ausfall(verband)
    await _sprich(verband.fahrer, [_quittieren(verband, ts)], FUEHRUNG)
    neu = await _ausfall(verband)

    assert neu != ts
    async with AsyncSessionLocal() as db:
        cv = await db.get(ConvoyVehicle, (verband.convoy_id, verband.lf))
        assert cv.alarm_quittiert_at is None
        assert cv.alarm_quittiert_von is None
    # Und die alte Quittung passt nicht auf den neuen Alarm.
    ws = await _sprich(verband.fahrer, [_quittieren(verband, ts, "q9")], FUEHRUNG)
    assert ws.acks()[0]["reason"] == "alarm-outdated"


async def test_der_zeitstempel_darf_anders_geschrieben_sein(verband, gesendet):
    # Gemeint ist der Zeitpunkt, nicht die Zeichenkette: Ein Client, der ihn als
    # „Z" zurückschickt oder in eine andere Zone rechnet, meint denselben Alarm.
    ts = await _ausfall(verband)
    anders = datetime.fromisoformat(ts).astimezone(timezone(timedelta(hours=2))).isoformat()
    ws = await _sprich(verband.fahrer, [_quittieren(verband, anders)], FUEHRUNG)

    assert ws.acks()[0]["result"] == "ok"


@pytest.mark.parametrize(
    ("frame", "grund"),
    [
        ({"vehicle_id": "kein-uuid"}, "invalid-vehicle"),
        ({"alarm_ts": "gestern"}, "invalid-alarm"),
        ({"alarm_ts": "2026-09-23T10:00:00"}, "invalid-alarm"),  # ohne Zone
        ({"vehicle_id": "00000000-0000-4000-8000-000000000000"}, "vehicle-not-in-convoy"),
    ],
)
async def test_eine_ablehnung_nennt_ihren_grund(verband, gesendet, frame, grund):
    ts = await _ausfall(verband)
    ws = await _sprich(verband.fahrer, [{**_quittieren(verband, ts), **frame}], FUEHRUNG)

    assert ws.acks()[0]["reason"] == grund


async def test_ein_lese_link_quittiert_nicht(verband, gesendet):
    ts = await _ausfall(verband)
    ws = await _sprich(verband.leser, [_quittieren(verband, ts)], FUEHRUNG)

    assert ws.acks()[0]["reason"] == "read-only"
    assert not [f for f in gesendet if f["type"] == "alarm_quittiert"]


async def test_im_web_quittiert_der_angemeldete_nutzer_mit_namen(verband, gesendet):
    ts = await _ausfall(verband)
    async with AsyncSessionLocal() as db:
        user = await db.get(User, verband.user_id)
    ws = FakeSocket([])
    await tracking_module._alarm_quittieren(
        str(verband.convoy_id), user, ws, _quittieren(verband, ts, "w1"), "geraet-web-01"
    )

    [ack] = ws.acks()
    assert ack["result"] == "ok"
    assert ack["applied"]["quittiert_von"] == "Anna Zugführer"
    async with AsyncSessionLocal() as db:
        cv = await db.get(ConvoyVehicle, (verband.convoy_id, verband.lf))
        assert cv.alarm_quittiert_von == "Anna Zugführer"


async def test_im_web_quittiert_man_den_eigenen_alarm_ebenso_wenig(verband, gesendet):
    ts = await _ausfall(verband)
    async with AsyncSessionLocal() as db:
        user = await db.get(User, verband.user_id)
    ws = FakeSocket([])
    await tracking_module._alarm_quittieren(
        str(verband.convoy_id), user, ws, _quittieren(verband, ts, "w2"), BESATZUNG
    )

    assert ws.acks()[0]["reason"] == "own-alert"
