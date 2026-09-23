"""Die Belegung am echten Fahrer-Link-Kanal (``track_ws``), gegen die Datenbank.

``test_fahrzeug_belegung.py`` prüft die Entscheidung; hier geht es um die
Verdrahtung: dass der Handler die Kennung aus dem Query-Parameter liest, vor dem
Schreiben prüft und eine fremde Position **nicht** in die Positionszeile lässt.
Die Verbindungen sind gestellt — sie liefern vorgegebene Frames und trennen dann.
"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect
from sqlalchemy import delete, select

from app.api.routes import track as track_module
from app.database import AsyncSessionLocal, engine
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.share_link import ConvoyShareLink
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_position import VehiclePosition
from app.services import belegung as belegung_modul
from app.services.belegung import Belegungen

APP = "app-geraet-0001"
WEB = "web-tab-000001"


@pytest.fixture(autouse=True)
async def reset_db_engine():
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def frische_belegungen(monkeypatch):
    monkeypatch.setattr(belegung_modul, "belegungen", Belegungen())


@pytest.fixture
async def verband():
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(email=f"beleg-{marker}@test.invalid", hashed_password="x", is_active=True)
        db.add(user)
        await db.flush()
        convoy = Convoy(name=f"Verband {marker}", owner_id=user.id)
        kdow = Vehicle(name=f"KdoW {marker}", callsign="Florian 10", owner_id=user.id)
        elw = Vehicle(name=f"ELW {marker}", owner_id=user.id)
        daneben = Vehicle(name=f"MTW {marker}", owner_id=user.id)
        db.add_all([convoy, kdow, elw, daneben])
        await db.flush()
        db.add_all([
            ConvoyVehicle(convoy_id=convoy.id, vehicle_id=kdow.id, position=0),
            ConvoyVehicle(convoy_id=convoy.id, vehicle_id=elw.id, position=1),
        ])
        link = ConvoyShareLink(
            convoy_id=convoy.id, slug=f"b{marker}", scope="driver", created_by_id=user.id
        )
        db.add(link)
        await db.commit()
        ids = SimpleNamespace(
            user_id=user.id, convoy_id=convoy.id, slug=link.slug,
            kdow=str(kdow.id), elw=str(elw.id), daneben=str(daneben.id),
        )

    yield ids

    async with AsyncSessionLocal() as db:
        await db.execute(delete(VehiclePosition).where(VehiclePosition.convoy_id == ids.convoy_id))
        await db.execute(delete(ConvoyShareLink).where(ConvoyShareLink.convoy_id == ids.convoy_id))
        await db.execute(delete(ConvoyVehicle).where(ConvoyVehicle.convoy_id == ids.convoy_id))
        await db.execute(delete(Convoy).where(Convoy.id == ids.convoy_id))
        await db.execute(delete(Vehicle).where(Vehicle.owner_id == ids.user_id))
        await db.execute(delete(User).where(User.id == ids.user_id))
        await db.commit()


class GestellteVerbindung:
    """Liefert die Frames, wartet danach bis ``trennen()``, sammelt, was ankommt."""

    def __init__(self, frames: list[dict]):
        self._frames = list(frames)
        self._getrennt = asyncio.Event()
        self.empfangen: list[dict] = []
        self.geschlossen: int | None = None

    async def accept(self):
        pass

    async def close(self, code: int = 1000):
        self.geschlossen = code

    async def send_json(self, data):
        self.empfangen.append(data)

    async def receive_json(self):
        if self._frames:
            return self._frames.pop(0)
        await self._getrennt.wait()
        raise WebSocketDisconnect()

    def trennen(self):
        self._getrennt.set()


async def _verbinden(slug: str, frames: list[dict], client: str | None):
    ws = GestellteVerbindung(frames)
    task = asyncio.create_task(track_module.track_ws(slug, ws, token=None, client=client))
    # Bis alle Frames verarbeitet sind — der Handler wartet dann auf den nächsten.
    for _ in range(200):
        await asyncio.sleep(0.01)
        if not ws._frames:
            break
    await asyncio.sleep(0.2)
    return ws, task


async def _position(ids, vehicle_id: str):
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(VehiclePosition).where(
                VehiclePosition.convoy_id == ids.convoy_id,
                VehiclePosition.vehicle_id == uuid.UUID(vehicle_id),
            )
        )).scalar_one_or_none()


def _pos(vehicle_id: str, lat: float) -> dict:
    return {"vehicle_id": vehicle_id, "lat": lat, "lon": 11.5}


async def test_im_browser_laesst_sich_der_kdow_der_app_nicht_mehr_senden(verband):
    """Der gemeldete Fall: KdoW in der App gewählt, im Browser noch einmal."""
    app, app_task = await _verbinden(
        verband.slug, [{"type": "belegen", "vehicle_id": verband.kdow}, _pos(verband.kdow, 48.1)], APP
    )
    web, web_task = await _verbinden(verband.slug, [_pos(verband.kdow, 50.0)], WEB)

    assert {"type": "belegungen", "vehicle_ids": [verband.kdow]} in web.empfangen
    assert {"type": "belegung_abgelehnt", "vehicle_id": verband.kdow} in web.empfangen
    pos = await _position(verband, verband.kdow)
    assert pos is not None and pos.lat == pytest.approx(48.1)

    for ws, task in ((app, app_task), (web, web_task)):
        ws.trennen()
        await task


async def test_ein_anderes_fahrzeug_bleibt_fuer_den_browser_frei(verband):
    app, app_task = await _verbinden(verband.slug, [{"type": "belegen", "vehicle_id": verband.kdow}], APP)
    web, web_task = await _verbinden(verband.slug, [_pos(verband.elw, 49.0)], WEB)

    assert not any(m.get("type") == "belegung_abgelehnt" for m in web.empfangen)
    assert {"type": "belegung", "vehicle_id": verband.elw, "belegt": True} in app.empfangen
    assert (await _position(verband, verband.elw)) is not None

    for ws, task in ((app, app_task), (web, web_task)):
        ws.trennen()
        await task


async def test_nach_dem_abwaehlen_ist_der_kdow_wieder_waehlbar(verband):
    app, app_task = await _verbinden(
        verband.slug,
        [{"type": "belegen", "vehicle_id": verband.kdow}, {"type": "freigeben", "vehicle_id": verband.kdow}],
        APP,
    )
    web, web_task = await _verbinden(verband.slug, [_pos(verband.kdow, 50.0)], WEB)

    assert {"type": "belegungen", "vehicle_ids": []} in web.empfangen
    assert not any(m.get("type") == "belegung_abgelehnt" for m in web.empfangen)
    assert (await _position(verband, verband.kdow)).lat == pytest.approx(50.0)

    for ws, task in ((app, app_task), (web, web_task)):
        ws.trennen()
        await task


async def test_ein_verbindungsabriss_gibt_das_fahrzeug_nicht_frei(verband):
    """Funkloch: die App ist weg, der KdoW bleibt ihrer."""
    app, app_task = await _verbinden(verband.slug, [{"type": "belegen", "vehicle_id": verband.kdow}], APP)
    app.trennen()
    await app_task

    web, web_task = await _verbinden(verband.slug, [_pos(verband.kdow, 50.0)], WEB)
    assert {"type": "belegung_abgelehnt", "vehicle_id": verband.kdow} in web.empfangen

    # … und die App kommt mit derselben Kennung zurück und sendet weiter.
    app2, app2_task = await _verbinden(verband.slug, [_pos(verband.kdow, 48.2)], APP)
    assert not any(m.get("type") == "belegung_abgelehnt" for m in app2.empfangen)
    assert (await _position(verband, verband.kdow)).lat == pytest.approx(48.2)

    for ws, task in ((web, web_task), (app2, app2_task)):
        ws.trennen()
        await task


async def test_eine_app_ohne_kennung_sendet_weiter_und_bekommt_nichts_neues(verband):
    """Eine noch nicht aktualisierte App aus dem Store."""
    web, web_task = await _verbinden(verband.slug, [{"type": "belegen", "vehicle_id": verband.kdow}], WEB)
    alt, alt_task = await _verbinden(verband.slug, [_pos(verband.kdow, 47.0)], None)

    assert alt.empfangen == [
        m for m in alt.empfangen if m.get("type") not in ("belegung", "belegungen", "belegung_abgelehnt")
    ]
    assert (await _position(verband, verband.kdow)).lat == pytest.approx(47.0)

    for ws, task in ((web, web_task), (alt, alt_task)):
        ws.trennen()
        await task


async def test_ein_fahrzeug_ausserhalb_des_verbands_wird_nicht_belegt(verband):
    web, web_task = await _verbinden(verband.slug, [{"type": "belegen", "vehicle_id": verband.daneben}], WEB)
    assert belegung_modul.belegungen.belegte(str(verband.convoy_id)) == []
    web.trennen()
    await web_task
