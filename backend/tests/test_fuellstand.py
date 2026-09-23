"""Füllstand: was eine Besatzung über Tank bzw. Akku meldet und was die Führung abliest.

Die Zusagen, die diese Tests halten: gemeldet wird in ganzen Prozent zwischen 0
und 100, „nicht gemeldet" bleibt von „leer" unterscheidbar, und Fahrer-Link und
angemeldeter Endpunkt nehmen dasselbe an.
"""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from app.api.deps import get_current_user
from app.api.routes import track as track_module
from app.api.routes import tracking as tracking_module
from app.database import AsyncSessionLocal, engine
from app.main import app
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services import fuellstand as fs
from app.services.tracking import tracking_manager


# ── Vokabular ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("wert", [0, 1, 50, 100])
def test_ganze_prozent_von_null_bis_hundert_gelten(wert):
    assert fs.normalisieren(wert) == wert


@pytest.mark.parametrize("wert", [-1, 101, 12.5, "50", None, True])
def test_alles_andere_wird_abgewiesen(wert):
    with pytest.raises(ValueError):
        fs.normalisieren(wert)


def test_endpunkt_prueft_dieselben_grenzen():
    from pydantic import ValidationError

    assert tracking_module.FuellstandUpdate(prozent=0).prozent == 0
    assert tracking_module.FuellstandUpdate(prozent=100).prozent == 100
    for falsch in (-1, 101):
        with pytest.raises(ValidationError):
            tracking_module.FuellstandUpdate(prozent=falsch)
    with pytest.raises(ValidationError):
        tracking_module.FuellstandUpdate()


# ── Melden und Ablesen ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
async def reset_db_engine():
    """Verbindungspool vor und nach jedem Test schließen (siehe test_track_betriebsstoff)."""
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture
async def verband():
    """Ein Marschverband mit einem Fahrzeug darin und einem daneben."""
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(email=f"fst-{marker}@test.invalid", hashed_password="x", is_active=True)
        db.add(user)
        await db.flush()
        convoy = Convoy(name=f"Verband {marker}", owner_id=user.id)
        im_verband = Vehicle(
            name=f"LF 10 {marker}", owner_id=user.id, tank_capacity_l=80.0, current_fuel_l=70.0
        )
        daneben = Vehicle(name=f"MTW {marker}", owner_id=user.id)
        db.add_all([convoy, im_verband, daneben])
        await db.flush()
        db.add(ConvoyVehicle(convoy_id=convoy.id, vehicle_id=im_verband.id, position=0))
        await db.commit()
        ids = SimpleNamespace(
            user_id=user.id,
            convoy_id=convoy.id,
            vehicle_id=im_verband.id,
            fremd_id=daneben.id,
        )

    yield ids

    async with AsyncSessionLocal() as db:
        await db.execute(delete(ConvoyVehicle).where(ConvoyVehicle.convoy_id == ids.convoy_id))
        await db.execute(delete(Convoy).where(Convoy.id == ids.convoy_id))
        await db.execute(delete(Vehicle).where(Vehicle.id.in_([ids.vehicle_id, ids.fremd_id])))
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
    await track_module._ingest_driver_fuellstand(
        verband.convoy_id, {"vehicle_id": str(verband.vehicle_id), "prozent": 25}
    )

    cv = await _cv(verband)
    assert cv.fuellstand_ist_prozent == 25
    assert cv.fuellstand_gemeldet_at is not None
    assert gesendet == [
        {
            "type": "fuellstand_update",
            "vehicle_id": str(verband.vehicle_id),
            "prozent": 25,
            "gemeldet_at": cv.fuellstand_gemeldet_at.isoformat(),
        }
    ]


async def test_meldung_laesst_die_stammdaten_stehen(verband, gesendet):
    # Der Fahrer-Link ist öffentlich — er darf den eingetragenen Stand am
    # Fahrzeug nicht umschreiben, nur die Meldung im Verband.
    await track_module._ingest_driver_fuellstand(
        verband.convoy_id, {"vehicle_id": str(verband.vehicle_id), "prozent": 10}
    )

    async with AsyncSessionLocal() as db:
        fahrzeug = await db.get(Vehicle, verband.vehicle_id)
    assert fahrzeug.current_fuel_l == 70.0


async def test_meldung_fuer_ein_fahrzeug_ausserhalb_des_verbands_verpufft(verband, gesendet):
    await track_module._ingest_driver_fuellstand(
        verband.convoy_id, {"vehicle_id": str(verband.fremd_id), "prozent": 50}
    )
    assert gesendet == []


@pytest.mark.parametrize("frame", [{"prozent": 150}, {"prozent": "halb"}, {}])
async def test_unplausible_meldung_laesst_die_alte_stehen(verband, gesendet, frame):
    await track_module._ingest_driver_fuellstand(
        verband.convoy_id, {"vehicle_id": str(verband.vehicle_id), **frame}
    )

    cv = await _cv(verband)
    assert cv.fuellstand_ist_prozent is None
    assert gesendet == []


async def test_leer_ist_eine_meldung(verband, gesendet):
    await track_module._ingest_driver_fuellstand(
        verband.convoy_id, {"vehicle_id": str(verband.vehicle_id), "prozent": 0}
    )

    cv = await _cv(verband)
    assert cv.fuellstand_ist_prozent == 0
    assert gesendet[0]["prozent"] == 0


# ── Angemeldeter Weg: die Führung trägt eine Funkmeldung nach ─────────────────

async def _patch_fuellstand(ids, body: dict, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    async def _access(*_args, **_kwargs):
        return SimpleNamespace(id=ids.convoy_id)

    monkeypatch.setattr(tracking_module, "get_convoy_access", _access)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=ids.user_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.patch(
                f"/api/convoys/{ids.convoy_id}/vehicles/{ids.vehicle_id}/fuellstand",
                json=body,
            )
    finally:
        app.dependency_overrides.clear()


async def test_fuehrung_traegt_gemeldeten_fuellstand_nach(verband, gesendet, monkeypatch):
    resp = await _patch_fuellstand(verband, {"prozent": 75}, monkeypatch)

    assert resp.status_code == 200
    assert resp.json()["prozent"] == 75
    cv = await _cv(verband)
    assert cv.fuellstand_ist_prozent == 75
    assert gesendet[-1]["type"] == "fuellstand_update"
    assert gesendet[-1]["prozent"] == 75


async def test_nachtrag_weist_unplausible_zahlen_ab(verband, gesendet, monkeypatch):
    resp = await _patch_fuellstand(verband, {"prozent": 120}, monkeypatch)

    assert resp.status_code == 422
    cv = await _cv(verband)
    assert cv.fuellstand_ist_prozent is None
    assert gesendet == []


async def test_nachtrag_verlangt_mindestens_die_rolle_fahrer(gesendet, monkeypatch):
    """Ein Beobachter trägt keinen Füllstand nach — dieselbe Schwelle wie bei der Stärke."""
    verlangt: list[str] = []

    async def _access(*_args, require: str = "read", **_kwargs):
        verlangt.append(require)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(tracking_module, "get_convoy_access", _access)

    class _Db:
        async def execute(self, *_a, **_k):
            return SimpleNamespace(scalar_one_or_none=lambda: cv)

        async def commit(self):
            pass

    cv = SimpleNamespace(fuellstand_ist_prozent=None, fuellstand_gemeldet_at=None)
    await tracking_module.update_vehicle_fuellstand(
        uuid.uuid4(),
        uuid.uuid4(),
        tracking_module.FuellstandUpdate(prozent=40),
        db=_Db(),
        current_user=SimpleNamespace(id=uuid.uuid4()),
    )

    assert verlangt == ["fahrer"]
    assert cv.fuellstand_ist_prozent == 40


# ── Ablesen: was in der Tracking-Ansicht ankommt ──────────────────────────────

async def test_tracking_ansicht_zeigt_die_meldung(verband, gesendet):
    await track_module._ingest_driver_fuellstand(
        verband.convoy_id, {"vehicle_id": str(verband.vehicle_id), "prozent": 40}
    )
    async with AsyncSessionLocal() as db:
        payload = await track_module._build_payload(verband.convoy_id, db)

    fahrzeug = payload.vehicles[0]
    assert fahrzeug.fuellstand_ist_prozent == 40
    assert fahrzeug.fuellstand_gemeldet_at is not None
    # Der eingetragene Stand kommt daneben unverändert mit.
    assert fahrzeug.current_fuel_l == 70.0


async def test_ohne_meldung_bleibt_der_fuellstand_leer(verband):
    async with AsyncSessionLocal() as db:
        payload = await track_module._build_payload(verband.convoy_id, db)

    fahrzeug = payload.vehicles[0]
    assert fahrzeug.fuellstand_ist_prozent is None
    assert fahrzeug.fuellstand_gemeldet_at is None
