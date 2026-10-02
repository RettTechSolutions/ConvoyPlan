"""Gemeinsame Fixtures der Aktionsseiten-Tests: eine Organisation mit Admin,
einem Konvoi aus zwei Fahrzeugen (Spitze und Schluss) und ein Client.

Per Import aktiviert (``from tests.aktionsseite_fixtures import ...``)."""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.organization import Organization, UserOrganization
from app.models.public_tracker import PublicTracker, VehiclePositionTrail
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services import positionsverlauf

# Was nie auf der öffentlichen Seite stehen darf — gesetzt, damit die Tests
# danach suchen können.
GEHEIMER_KONVOINAME = "KV 3 Los B Ladeliste intern"
RUFNAME = "Florian Landshut 11/1"
TELEFON = "+49 171 5550123"


def _token(user_id, tv: int, **extra) -> str:
    claims = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "typ": "access",
        "tv": tv,
        **extra,
    }
    return _jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
async def reset_db_engine():
    positionsverlauf.vergessen()
    from app.api.routes import aktionsseite as routen

    routen._cache.clear()
    yield
    await engine.dispose()


@pytest.fixture
async def client():
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def aktion():
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        admin = User(email=f"akt-ad-{marker}@test.invalid", hashed_password="x")
        fahrer = User(email=f"akt-fa-{marker}@test.invalid", hashed_password="x")
        db.add_all([admin, fahrer])
        await db.flush()
        org = Organization(name=f"Aktion {marker}", slug=f"a{marker[:7]}", owner_id=admin.id)
        db.add(org)
        await db.flush()
        db.add_all([
            UserOrganization(user_id=admin.id, organization_id=org.id, role="admin"),
            UserOrganization(user_id=fahrer.id, organization_id=org.id, role="fahrer"),
        ])
        convoy = Convoy(name=GEHEIMER_KONVOINAME, owner_id=admin.id, organization_id=org.id)
        spitze = Vehicle(name="LKW 1", callsign=RUFNAME, owner_id=admin.id)
        schluss = Vehicle(name="LKW 12", callsign="Florian Landshut 11/12", owner_id=admin.id)
        db.add_all([convoy, spitze, schluss])
        await db.flush()
        db.add_all([
            ConvoyVehicle(
                convoy_id=convoy.id, vehicle_id=spitze.id, position=0,
                sonderfunktion="spitzenführer", mobile_phone=TELEFON,
            ),
            ConvoyVehicle(convoy_id=convoy.id, vehicle_id=schluss.id, position=1),
        ])
        await db.commit()
        ids = SimpleNamespace(
            org_id=org.id,
            convoy_id=convoy.id,
            spitze=spitze.id,
            schluss=schluss.id,
            admin=_token(admin.id, admin.token_version, org_id=str(org.id), org_slug=org.slug, role="admin"),
            fahrer=_token(fahrer.id, fahrer.token_version, org_id=str(org.id), org_slug=org.slug, role="fahrer"),
            users=[admin.id, fahrer.id],
        )
    yield ids
    async with AsyncSessionLocal() as db:
        await db.execute(delete(PublicTracker).where(PublicTracker.organization_id == ids.org_id))
        await db.execute(delete(VehiclePositionTrail).where(VehiclePositionTrail.convoy_id == ids.convoy_id))
        await db.execute(delete(ConvoyVehicle).where(ConvoyVehicle.convoy_id == ids.convoy_id))
        await db.execute(delete(Convoy).where(Convoy.id == ids.convoy_id))
        await db.execute(delete(Vehicle).where(Vehicle.id.in_([ids.spitze, ids.schluss])))
        await db.execute(delete(UserOrganization).where(UserOrganization.organization_id == ids.org_id))
        await db.execute(delete(Organization).where(Organization.id == ids.org_id))
        await db.execute(delete(User).where(User.id.in_(ids.users)))
        await db.commit()


async def seite_anlegen(client, aktion, **felder) -> dict:
    body = {
        "title": "Weihnachtskonvois 2026",
        "theme": "weihnachten",
        "delay_minutes": 120,
        "convoys": [
            {"convoy_id": str(aktion.convoy_id), "display_name": "Konvoi Bosnien",
             "destination_label": "Tuzla"},
        ],
        **felder,
    }
    r = await client.post("/api/org/aktionsseiten", json=body, headers=h(aktion.admin))
    assert r.status_code == 201, r.text
    return r.json()


async def verlauf(aktion, punkte: list[tuple[uuid.UUID, datetime, float, float]]) -> None:
    """Punkte direkt in den Verlauf legen — mit Zeitstempeln in der
    Vergangenheit, die über die echten Schreibstellen nicht entstehen."""
    async with AsyncSessionLocal() as db:
        db.add_all([
            VehiclePositionTrail(
                convoy_id=aktion.convoy_id, vehicle_id=v, recorded_at=t, lat=lat, lon=lon
            )
            for v, t, lat, lon in punkte
        ])
        await db.commit()


def fahrt(fahrzeug, ende: datetime, minuten: int, lat=48.5, lon0=12.1):
    """Ein Punkt pro Minute nach Osten, endend bei ``ende``."""
    return [
        (fahrzeug, ende - timedelta(minutes=minuten - 1 - i), lat, lon0 + i * 0.01)
        for i in range(minuten)
    ]
