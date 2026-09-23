"""Betriebsstoff in der Tracking-Ansicht: Tank- bzw. Akkustand je Fahrzeug.

Die Companion-App zeigt der Verbandsführung neben der Stärke den eingetragenen
Füllstand. Die Zusage, die diese Tests halten: Es kommt nur der Satz der
eigenen Antriebsart über den Draht, und was nicht eingetragen ist, bleibt None.
"""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from app.api.routes import track as track_module
from app.database import AsyncSessionLocal, engine
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.user import User
from app.models.vehicle import Vehicle


@pytest.fixture(autouse=True)
async def reset_db_engine():
    """Verbindungspool vor und nach jedem Test schließen (siehe mcp_fixtures).

    Auch vorher: Ein Modul, das vor diesem läuft und die Datenbank ohne eigenes
    ``dispose()`` anfasst, hinterlässt sonst eine Verbindung der fremden Loop."""
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture
async def verband():
    """Ein Verband mit einem Verbrenner und einem E-Fahrzeug."""
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(email=f"bst-{marker}@test.invalid", hashed_password="x", is_active=True)
        db.add(user)
        await db.flush()
        convoy = Convoy(name=f"Verband {marker}", owner_id=user.id)
        lf = Vehicle(
            name=f"LF 10 {marker}",
            owner_id=user.id,
            propulsion="combustion",
            tank_capacity_l=80.0,
            current_fuel_l=45.0,
            fuel_consumption_l100km=12.5,
            # Überbleibsel aus einer Fehleingabe — darf nicht mitkommen.
            battery_capacity_kwh=60.0,
        )
        elw = Vehicle(
            name=f"ELW {marker}",
            owner_id=user.id,
            propulsion="electric",
            battery_capacity_kwh=60.0,
            current_charge_kwh=40.5,
            consumption_kwh_100km=20.0,
            # Stehengeblieben aus der Zeit vor dem Umstellen auf elektrisch.
            tank_capacity_l=70.0,
            current_fuel_l=30.0,
        )
        db.add_all([convoy, lf, elw])
        await db.flush()
        db.add_all([
            ConvoyVehicle(convoy_id=convoy.id, vehicle_id=lf.id, position=0),
            ConvoyVehicle(convoy_id=convoy.id, vehicle_id=elw.id, position=1),
        ])
        await db.commit()
        ids = SimpleNamespace(user_id=user.id, convoy_id=convoy.id, lf_id=lf.id, elw_id=elw.id)

    yield ids

    async with AsyncSessionLocal() as db:
        await db.execute(delete(ConvoyVehicle).where(ConvoyVehicle.convoy_id == ids.convoy_id))
        await db.execute(delete(Convoy).where(Convoy.id == ids.convoy_id))
        await db.execute(delete(Vehicle).where(Vehicle.id.in_([ids.lf_id, ids.elw_id])))
        await db.execute(delete(User).where(User.id == ids.user_id))
        await db.commit()


async def _fahrzeuge(convoy_id) -> dict:
    async with AsyncSessionLocal() as db:
        payload = await track_module._build_payload(convoy_id, db)
    return {v.id: v for v in payload.vehicles}


async def test_verbrenner_liefert_den_tanksatz(verband):
    lf = (await _fahrzeuge(verband.convoy_id))[verband.lf_id]

    assert lf.propulsion == "combustion"
    assert (lf.tank_capacity_l, lf.current_fuel_l, lf.fuel_consumption_l100km) == (80.0, 45.0, 12.5)
    assert lf.battery_capacity_kwh is None
    assert lf.current_charge_kwh is None
    assert lf.consumption_kwh_100km is None


async def test_e_fahrzeug_liefert_nur_den_akkusatz(verband):
    elw = (await _fahrzeuge(verband.convoy_id))[verband.elw_id]

    assert elw.propulsion == "electric"
    assert (elw.battery_capacity_kwh, elw.current_charge_kwh, elw.consumption_kwh_100km) == (60.0, 40.5, 20.0)
    assert elw.tank_capacity_l is None
    assert elw.current_fuel_l is None
    assert elw.fuel_consumption_l100km is None


async def test_ohne_eintrag_bleibt_der_fuellstand_leer(verband):
    async with AsyncSessionLocal() as db:
        lf = await db.get(Vehicle, verband.lf_id)
        lf.current_fuel_l = None
        await db.commit()

    lf = (await _fahrzeuge(verband.convoy_id))[verband.lf_id]
    assert lf.current_fuel_l is None
    assert lf.tank_capacity_l == 80.0
