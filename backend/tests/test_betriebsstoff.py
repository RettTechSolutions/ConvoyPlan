"""Betriebsstofflage: was eine Besatzung meldet und was die Führung abliest.

Die Zusagen dieser Tests: „nicht gemeldet" und „leer" bleiben unterscheidbar,
eine unplausible Meldung lässt die alte stehen, und eine neue ersetzt die
alte ganz — ein Tank aus der vorigen Meldung neben dem Füllstand der neuen
wäre eine Lage, die so niemand gemeldet hat.
"""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from app.api.routes import track as track_module
from app.database import AsyncSessionLocal, engine
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.organization import Organization, UserOrganization
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services import betriebsstoff as bs
from app.services.tracking import tracking_manager


# ── Vokabular ─────────────────────────────────────────────────────────────────

def test_ohne_jede_angabe_gibt_es_keine_meldung():
    assert bs.normalisieren(None, None, None) is None


def test_fehlende_angaben_bleiben_unbekannt_statt_null():
    # Anders als bei der Stärke: ein fehlender Tank ist unbekannt, nicht leer.
    assert bs.normalisieren(None, None, 40) == (None, None, 40)


def test_leerer_tank_ist_eine_angabe():
    assert bs.normalisieren(30, 200, 0) == (30.0, 200, 0)


def test_verbrauch_wird_auf_eine_nachkommastelle_gerundet():
    assert bs.normalisieren(28.46, None, None) == (28.5, None, None)


@pytest.mark.parametrize(
    "verbrauch, tank, fuellstand",
    [
        (0, None, None),  # Verbrauch 0 ist ein Tippfehler
        (151, None, None),
        (None, 0, None),  # Tank 0 ebenso
        (None, 1501, None),
        (None, None, -1),
        (None, None, 101),
        (None, 200.5, None),  # Liter und Prozent sind ganze Zahlen
        ("30", None, None),
        (True, None, None),
        (float("nan"), None, None),
    ],
)
def test_unplausible_angaben_werden_abgewiesen(verbrauch, tank, fuellstand):
    with pytest.raises(ValueError):
        bs.normalisieren(verbrauch, tank, fuellstand)


def test_ganzzahlige_kommazahl_ist_eine_ganze_zahl():
    # JSON kennt keinen Unterschied zwischen 200 und 200.0.
    assert bs.normalisieren(None, 200.0, 50.0) == (None, 200, 50)


def test_reichweite():
    # 100 l bei 30 l/100 km
    assert bs.reichweite_km(30, 200, 50) == pytest.approx(333.33, abs=0.01)
    assert bs.reichweite_km(None, 200, 50) is None
    assert bs.reichweite_km(30, 200, 0) == 0

# ── Melden und Ablesen ────────────────────────────────────────────────────────



@pytest.fixture(autouse=True)
async def reset_db_engine():
    """Verbindungspool nach jedem Test schließen — sonst gehört eine gepoolte
    asyncpg-Verbindung der Event-Loop des vorigen Tests (siehe mcp_fixtures)."""
    yield
    await engine.dispose()


@pytest.fixture
async def verband():
    """Ein Marschverband mit einem Fahrzeug darin und einem daneben."""
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(email=f"bst-{marker}@test.invalid", hashed_password="x", is_active=True)
        db.add(user)
        await db.flush()
        org = Organization(name=f"Org {marker}", slug=f"org-{marker}", owner_id=user.id)
        db.add(org)
        await db.flush()
        db.add(UserOrganization(user_id=user.id, organization_id=org.id, role="planer"))
        convoy = Convoy(name=f"Verband {marker}", owner_id=user.id, organization_id=org.id)
        im_verband = Vehicle(name=f"LF 10 {marker}", callsign="Florian 1", owner_id=user.id)
        daneben = Vehicle(name=f"MTW {marker}", owner_id=user.id)
        db.add_all([convoy, im_verband, daneben])
        await db.flush()
        db.add(ConvoyVehicle(convoy_id=convoy.id, vehicle_id=im_verband.id, position=0))
        await db.commit()
        ids = SimpleNamespace(
            user_id=user.id,
            org_id=org.id,
            org_slug=org.slug,
            convoy_id=convoy.id,
            vehicle_id=im_verband.id,
            fremd_id=daneben.id,
        )

    yield ids

    async with AsyncSessionLocal() as db:
        await db.execute(delete(ConvoyVehicle).where(ConvoyVehicle.convoy_id == ids.convoy_id))
        await db.execute(delete(Convoy).where(Convoy.id == ids.convoy_id))
        await db.execute(
            delete(Vehicle).where(Vehicle.id.in_([ids.vehicle_id, ids.fremd_id]))
        )
        await db.execute(
            delete(UserOrganization).where(UserOrganization.organization_id == ids.org_id)
        )
        await db.execute(delete(Organization).where(Organization.id == ids.org_id))
        await db.execute(delete(User).where(User.id == ids.user_id))
        await db.commit()


@pytest.fixture
def gesendet(monkeypatch):
    """Fängt ab, was an die geöffneten Tracking-Ansichten ginge."""
    frames: list[dict] = []

    async def _broadcast(_convoy_id, payload):
        frames.append(payload)

    monkeypatch.setattr(tracking_manager, "broadcast", _broadcast)
    return frames


async def _cv(ids) -> ConvoyVehicle:
    async with AsyncSessionLocal() as db:
        return await db.get(ConvoyVehicle, (ids.convoy_id, ids.vehicle_id))


# ── Fahrer-Link: die Besatzung meldet ─────────────────────────────────────────

async def test_besatzung_meldet_ueber_den_fahrer_link(verband, gesendet):
    await track_module._ingest_driver_betriebsstoff(
        verband.convoy_id,
        {"vehicle_id": str(verband.vehicle_id), "verbrauch": 30.5, "tank": 200, "fuellstand": 75},
    )

    cv = await _cv(verband)
    assert (cv.betriebsstoff_verbrauch, cv.betriebsstoff_tank, cv.betriebsstoff_fuellstand) == (30.5, 200, 75)
    assert cv.betriebsstoff_gemeldet_at is not None
    assert gesendet == [
        {
            "type": "betriebsstoff_update",
            "vehicle_id": str(verband.vehicle_id),
            "verbrauch": 30.5,
            "tank": 200,
            "fuellstand": 75,
            "gemeldet_at": cv.betriebsstoff_gemeldet_at.isoformat(),
        }
    ]


async def test_meldung_fuer_ein_fahrzeug_ausserhalb_des_verbands_verpufft(verband, gesendet):
    await track_module._ingest_driver_betriebsstoff(
        verband.convoy_id,
        {"vehicle_id": str(verband.fremd_id), "fuellstand": 50},
    )
    assert gesendet == []


async def test_unplausible_meldung_laesst_die_alte_stehen(verband, gesendet):
    await track_module._ingest_driver_betriebsstoff(
        verband.convoy_id,
        {"vehicle_id": str(verband.vehicle_id), "tank": 200, "fuellstand": 50},
    )
    await track_module._ingest_driver_betriebsstoff(
        verband.convoy_id,
        {"vehicle_id": str(verband.vehicle_id), "tank": 200, "fuellstand": 250},
    )

    cv = await _cv(verband)
    assert cv.betriebsstoff_fuellstand == 50
    assert len(gesendet) == 1


async def test_meldung_ohne_angabe_ist_keine(verband, gesendet):
    await track_module._ingest_driver_betriebsstoff(
        verband.convoy_id, {"vehicle_id": str(verband.vehicle_id)}
    )

    cv = await _cv(verband)
    assert cv.betriebsstoff_gemeldet_at is None
    assert gesendet == []


async def test_neue_meldung_ersetzt_die_alte_ganz(verband, gesendet):
    await track_module._ingest_driver_betriebsstoff(
        verband.convoy_id,
        {"vehicle_id": str(verband.vehicle_id), "verbrauch": 30, "tank": 200, "fuellstand": 50},
    )
    await track_module._ingest_driver_betriebsstoff(
        verband.convoy_id,
        {"vehicle_id": str(verband.vehicle_id), "fuellstand": 20},
    )

    cv = await _cv(verband)
    assert (cv.betriebsstoff_verbrauch, cv.betriebsstoff_tank, cv.betriebsstoff_fuellstand) == (None, None, 20)


async def test_leerer_tank_ist_eine_meldung(verband, gesendet):
    await track_module._ingest_driver_betriebsstoff(
        verband.convoy_id, {"vehicle_id": str(verband.vehicle_id), "fuellstand": 0}
    )

    cv = await _cv(verband)
    assert cv.betriebsstoff_fuellstand == 0
    assert gesendet[0]["fuellstand"] == 0


# ── Ablesen: was in der Tracking-Ansicht ankommt ──────────────────────────────

async def test_tracking_ansicht_zeigt_die_meldung(verband):
    async with AsyncSessionLocal() as db:
        cv = await db.get(ConvoyVehicle, (verband.convoy_id, verband.vehicle_id))
        cv.betriebsstoff_verbrauch, cv.betriebsstoff_tank, cv.betriebsstoff_fuellstand = 28.5, 150, 40
        await db.commit()

        payload = await track_module._build_payload(verband.convoy_id, db)

    fahrzeug = payload.vehicles[0]
    assert (fahrzeug.betriebsstoff_verbrauch, fahrzeug.betriebsstoff_tank, fahrzeug.betriebsstoff_fuellstand) == (28.5, 150, 40)


async def test_ohne_meldung_bleibt_die_lage_leer(verband):
    async with AsyncSessionLocal() as db:
        payload = await track_module._build_payload(verband.convoy_id, db)

    fahrzeug = payload.vehicles[0]
    assert fahrzeug.betriebsstoff_fuellstand is None
    assert fahrzeug.betriebsstoff_gemeldet_at is None


async def test_stammdaten_stehen_als_soll_daneben(verband):
    # Tank und Verbrauch aus der Planung kommen mit, damit die App vorbelegen
    # kann — und sie bleiben unberührt, wenn die Besatzung etwas anderes meldet.
    async with AsyncSessionLocal() as db:
        fz = await db.get(Vehicle, verband.vehicle_id)
        fz.tank_capacity_l, fz.fuel_consumption_l100km = 300.0, 35.0
        await db.commit()

    await track_module._ingest_driver_betriebsstoff(
        verband.convoy_id, {"vehicle_id": str(verband.vehicle_id), "tank": 200, "fuellstand": 60}
    )

    async with AsyncSessionLocal() as db:
        payload = await track_module._build_payload(verband.convoy_id, db)
        fz = await db.get(Vehicle, verband.vehicle_id)

    fahrzeug = payload.vehicles[0]
    assert fahrzeug.propulsion == "combustion"
    assert (fahrzeug.tank_capacity_l, fahrzeug.fuel_consumption_l100km) == (300.0, 35.0)
    assert fahrzeug.betriebsstoff_tank == 200
    # Die Meldung schreibt nicht in die Stammdaten — die Planung rechnet weiter
    # mit dem, was dort eingetragen ist.
    assert fz.tank_capacity_l == 300.0
