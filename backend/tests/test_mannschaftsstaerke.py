"""Mannschaftsstärke: was eine Besatzung meldet und was die Führung abliest.

Die Zusage, die diese Tests halten: „nicht gemeldet" und „niemand an Bord"
bleiben unterscheidbar. Ein Fahrzeug, das 0/0/0 meldet, ist leer; eines, das
nichts gemeldet hat, ist unbekannt — und die Führung darf das eine nie für das
andere halten.
"""

import pytest

from app.services import staerke as st


# ── Vokabular ─────────────────────────────────────────────────────────────────

def test_ohne_jede_angabe_gibt_es_keine_staerke():
    assert st.normalisieren(None, None, None) is None


def test_null_personen_ist_eine_angabe_und_kein_fehlen():
    # Der Unterschied, um den es in dieser Datei geht.
    assert st.normalisieren(0, 0, 0) == (0, 0, 0)


def test_teilangabe_zaehlt_die_fehlenden_als_null():
    # Wer nur Unterführer und Mannschaften meldet, hat keinen Führer an Bord.
    assert st.normalisieren(None, 1, 8) == (0, 1, 8)


def test_negative_staerke_wird_abgewiesen():
    with pytest.raises(ValueError):
        st.normalisieren(0, -1, 8)


def test_unplausibel_grosse_staerke_wird_abgewiesen():
    with pytest.raises(ValueError):
        st.normalisieren(0, 1, 100)


def test_gesamt_ist_die_summe_der_drei_zahlen():
    assert st.gesamt(0, 1, 8) == 9


def test_gesamt_ohne_meldung_bleibt_unbekannt():
    # Nicht 0 — sonst läse die Führung „keine Besatzung" statt „keine Meldung".
    assert st.gesamt(None, None, None) is None


# ── Eingabeprüfung des Endpunkts ──────────────────────────────────────────────

def test_endpunkt_weist_negative_zahl_ab():
    from pydantic import ValidationError

    from app.api.routes.tracking import StaerkeUpdate

    with pytest.raises(ValidationError):
        StaerkeUpdate(fuehrer=0, unterfuehrer=1, mannschaften=-3)


def test_endpunkt_weist_unplausibel_grosse_zahl_ab():
    from pydantic import ValidationError

    from app.api.routes.tracking import StaerkeUpdate

    with pytest.raises(ValidationError):
        StaerkeUpdate(fuehrer=0, unterfuehrer=1, mannschaften=100)


def test_endpunkt_nimmt_die_leermeldung_an():
    from app.api.routes.tracking import StaerkeUpdate

    daten = StaerkeUpdate(fuehrer=0, unterfuehrer=0, mannschaften=0)
    assert (daten.fuehrer, daten.unterfuehrer, daten.mannschaften) == (0, 0, 0)


# ── Melden und Ablesen ────────────────────────────────────────────────────────
#
# Datenbankgestützt, wie die MCP-Tests: geprüft wird, was in der Zeile landet
# und was über den Draht geht. Mit einer Attrappe prüfte man die Attrappe.

import uuid
from types import SimpleNamespace

from sqlalchemy import delete

from app.api.deps import get_current_user
from app.api.routes import track as track_module
from app.api.routes import tracking as tracking_module
from app.database import AsyncSessionLocal, engine
from app.main import app
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.organization import Organization, UserOrganization
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.tracking import tracking_manager


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
        user = User(email=f"stk-{marker}@test.invalid", hashed_password="x", is_active=True)
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
    await track_module._ingest_driver_staerke(
        verband.convoy_id,
        {"vehicle_id": str(verband.vehicle_id), "fuehrer": 0, "unterfuehrer": 1, "mannschaften": 8},
    )

    cv = await _cv(verband)
    assert (cv.staerke_ist_fuehrer, cv.staerke_ist_unterfuehrer, cv.staerke_ist_mannschaften) == (0, 1, 8)
    assert cv.staerke_gemeldet_at is not None
    assert gesendet == [
        {
            "type": "staerke_update",
            "vehicle_id": str(verband.vehicle_id),
            "fuehrer": 0,
            "unterfuehrer": 1,
            "mannschaften": 8,
            "gesamt": 9,
        }
    ]


async def test_meldung_fuer_ein_fahrzeug_ausserhalb_des_verbands_verpufft(verband, gesendet):
    # Der Fahrer-Link gilt für genau einen Verband; ein fremdes Fahrzeug darf er
    # nicht anfassen, auch wenn seine Kennung stimmt.
    await track_module._ingest_driver_staerke(
        verband.convoy_id,
        {"vehicle_id": str(verband.fremd_id), "fuehrer": 0, "unterfuehrer": 1, "mannschaften": 8},
    )
    assert gesendet == []


async def test_unplausible_meldung_laesst_die_alte_stehen(verband, gesendet):
    await track_module._ingest_driver_staerke(
        verband.convoy_id,
        {"vehicle_id": str(verband.vehicle_id), "fuehrer": 0, "unterfuehrer": 1, "mannschaften": 500},
    )

    cv = await _cv(verband)
    assert cv.staerke_ist_mannschaften is None
    assert gesendet == []


async def test_leermeldung_null_ist_eine_meldung(verband, gesendet):
    # „Fahrzeug fährt unbesetzt" muss meldbar sein und darf nicht als
    # „nichts gemeldet" in der Zeile landen.
    await track_module._ingest_driver_staerke(
        verband.convoy_id,
        {"vehicle_id": str(verband.vehicle_id), "fuehrer": 0, "unterfuehrer": 0, "mannschaften": 0},
    )

    cv = await _cv(verband)
    assert cv.staerke_ist_fuehrer == 0
    assert cv.staerke_gemeldet_at is not None
    assert gesendet[0]["gesamt"] == 0


# ── Angemeldeter Weg: die Führung trägt eine Funkmeldung nach ─────────────────

async def _patch_staerke(ids, body: dict, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    async def _access(*_args, **_kwargs):
        return SimpleNamespace(id=ids.convoy_id)

    monkeypatch.setattr(tracking_module, "get_convoy_access", _access)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=ids.user_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.patch(
                f"/api/convoys/{ids.convoy_id}/vehicles/{ids.vehicle_id}/staerke",
                json=body,
            )
    finally:
        app.dependency_overrides.clear()


async def test_fuehrung_traegt_gemeldete_staerke_nach(verband, gesendet, monkeypatch):
    resp = await _patch_staerke(
        verband, {"fuehrer": 1, "unterfuehrer": 2, "mannschaften": 12}, monkeypatch
    )

    assert resp.status_code == 200
    assert resp.json()["gesamt"] == 15
    cv = await _cv(verband)
    assert (cv.staerke_ist_fuehrer, cv.staerke_ist_unterfuehrer, cv.staerke_ist_mannschaften) == (1, 2, 12)


async def test_nachtrag_weist_unplausible_zahlen_ab(verband, gesendet, monkeypatch):
    resp = await _patch_staerke(
        verband, {"fuehrer": 0, "unterfuehrer": 1, "mannschaften": -3}, monkeypatch
    )

    assert resp.status_code == 422
    cv = await _cv(verband)
    assert cv.staerke_ist_mannschaften is None


# ── Ablesen: was in der Tracking-Ansicht ankommt ──────────────────────────────

async def test_tracking_ansicht_zeigt_soll_und_ist(verband):
    async with AsyncSessionLocal() as db:
        cv = await db.get(ConvoyVehicle, (verband.convoy_id, verband.vehicle_id))
        cv.staerke_soll_fuehrer, cv.staerke_soll_unterfuehrer, cv.staerke_soll_mannschaften = 0, 1, 8
        cv.staerke_ist_fuehrer, cv.staerke_ist_unterfuehrer, cv.staerke_ist_mannschaften = 0, 1, 6
        await db.commit()

        payload = await track_module._build_payload(verband.convoy_id, db)

    fahrzeug = payload.vehicles[0]
    assert (fahrzeug.staerke_soll_fuehrer, fahrzeug.staerke_soll_unterfuehrer, fahrzeug.staerke_soll_mannschaften) == (0, 1, 8)
    assert (fahrzeug.staerke_ist_fuehrer, fahrzeug.staerke_ist_unterfuehrer, fahrzeug.staerke_ist_mannschaften) == (0, 1, 6)


async def test_ohne_meldung_bleibt_die_ist_staerke_leer(verband):
    # Die Ansicht darf hier nichts hinschreiben, was wie eine Meldung aussieht.
    async with AsyncSessionLocal() as db:
        payload = await track_module._build_payload(verband.convoy_id, db)

    fahrzeug = payload.vehicles[0]
    assert fahrzeug.staerke_ist_fuehrer is None
    assert fahrzeug.staerke_ist_unterfuehrer is None
    assert fahrzeug.staerke_ist_mannschaften is None


# ── Planung: das Soll ─────────────────────────────────────────────────────────

async def _patch_im_verband(ids, body: dict, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import get_org_context
    from app.api.routes import convoys as convoys_module  # noqa: F401  (Route registrieren)

    async def _ctx():
        async with AsyncSessionLocal() as db:
            user = await db.get(User, ids.user_id)
            org = await db.get(Organization, ids.org_id)
            return (user, org, "planer")

    app.dependency_overrides[get_org_context] = _ctx
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.patch(
                f"/api/convoys/{ids.convoy_id}/vehicles/{ids.vehicle_id}",
                json=body,
            )
    finally:
        app.dependency_overrides.clear()


async def test_planer_traegt_die_sollstaerke_ein(verband, monkeypatch):
    resp = await _patch_im_verband(
        verband,
        {"staerke_soll_fuehrer": 0, "staerke_soll_unterfuehrer": 1, "staerke_soll_mannschaften": 8},
        monkeypatch,
    )

    assert resp.status_code == 200
    cv = await _cv(verband)
    assert (cv.staerke_soll_fuehrer, cv.staerke_soll_unterfuehrer, cv.staerke_soll_mannschaften) == (0, 1, 8)


async def test_soll_setzen_ruehrt_die_meldung_nicht_an(verband, monkeypatch):
    """Zwei Zahlenpaare, zwei Zuständige — der Planer überschreibt keine Meldung."""
    async with AsyncSessionLocal() as db:
        cv = await db.get(ConvoyVehicle, (verband.convoy_id, verband.vehicle_id))
        cv.staerke_ist_fuehrer, cv.staerke_ist_unterfuehrer, cv.staerke_ist_mannschaften = 0, 1, 6
        await db.commit()

    await _patch_im_verband(
        verband,
        {"staerke_soll_fuehrer": 0, "staerke_soll_unterfuehrer": 1, "staerke_soll_mannschaften": 8},
        monkeypatch,
    )

    cv = await _cv(verband)
    assert (cv.staerke_ist_fuehrer, cv.staerke_ist_unterfuehrer, cv.staerke_ist_mannschaften) == (0, 1, 6)


async def test_teilaenderung_laesst_ungenannte_felder_stehen(verband, monkeypatch):
    # PATCH heißt PATCH: was nicht im Rumpf steht, bleibt wie es war.
    await _patch_im_verband(
        verband, {"sonderfunktion": "spitzenfuehrer", "staerke_soll_mannschaften": 8}, monkeypatch
    )
    await _patch_im_verband(verband, {"staerke_soll_mannschaften": 9}, monkeypatch)

    cv = await _cv(verband)
    assert cv.sonderfunktion == "spitzenfuehrer"
    assert cv.staerke_soll_mannschaften == 9


async def test_unplausibles_soll_wird_abgewiesen(verband, monkeypatch):
    resp = await _patch_im_verband(verband, {"staerke_soll_mannschaften": 100}, monkeypatch)

    assert resp.status_code == 422
    cv = await _cv(verband)
    assert cv.staerke_soll_mannschaften is None
