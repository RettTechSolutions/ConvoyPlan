"""Lange Routen: GraphHopper darf rechnen, und ein Abbruch heißt nicht „nicht verfügbar".

Gemeldet: Bayern → Shkodër über Bari–Durrës, 3.250 km. Jede Berechnung endete
nach 30 s mit „Routing-Dienst nicht verfügbar", obwohl GraphHopper lief — seit
der Graph ohne CH auskommt (graphhopper/entrypoint.sh), rechnet er lange Routen
flexibel, und das dauerte länger als die fest eingebaute Frist. Die Zusagen:

- die Frist kommt aus ``GRAPHHOPPER_TIMEOUT_S`` und ist deutlich länger als 30 s,
  nur das Verbinden bleibt kurz;
- ein Abbruch nach der Frist ist ein eigener Fehler (504, mit der Frist und dem
  Hinweis auf die Einstellung) und wird nicht ohne Gewicht/Fähre wiederholt;
- ein nicht erreichbarer Dienst bleibt „nicht verfügbar".
"""
import uuid
from types import SimpleNamespace

import httpx
import pytest
from geoalchemy2.shape import from_shape
from httpx import ASGITransport, AsyncClient
from shapely.geometry import Point
from sqlalchemy import delete

from app.api.deps import get_current_user, get_token_data
from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.main import app
from app.models.convoy import Convoy
from app.models.organization import Organization, UserOrganization
from app.models.route import Route
from app.models.user import User
from app.services import routing as routing_svc

PUNKTE = [{"lat": 47.80, "lon": 11.0}, {"lat": 42.07, "lon": 19.51}]


def _graphhopper(fehler: Exception, gesendet: list, fristen: list):
    class _Client:
        def __init__(self, *a, timeout=None, **k):
            fristen.append(timeout)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            gesendet.append(json)
            raise fehler

    return SimpleNamespace(AsyncClient=_Client)


def test_die_frist_ist_laenger_als_frueher():
    assert settings.graphhopper_timeout_s > 30


async def test_frist_aus_der_einstellung_verbinden_bleibt_kurz(monkeypatch):
    gesendet: list = []
    fristen: list = []
    monkeypatch.setattr(settings, "graphhopper_timeout_s", 240.0)
    monkeypatch.setattr(routing_svc, "httpx", _graphhopper(httpx.ReadTimeout("zu lang"), gesendet, fristen))
    with pytest.raises(routing_svc.RoutingTimeoutError):
        await routing_svc.calculate_route(PUNKTE, {"max_weight_t": 18.0})
    [frist] = fristen
    assert frist.read == 240.0
    assert frist.connect <= 10.0
    # Kein Rückfall ohne Gewicht oder Fähre: der stellte dieselbe lange Anfrage noch einmal.
    assert len(gesendet) == 1


@pytest.fixture(autouse=True)
async def reset_db_engine():
    yield
    await engine.dispose()


@pytest.fixture
async def verband():
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(email=f"frist-{marker}@test.invalid", hashed_password="x", is_active=True)
        db.add(user)
        await db.flush()
        org = Organization(name=f"Org {marker}", slug=f"org-{marker}", owner_id=user.id)
        db.add(org)
        await db.flush()
        db.add(UserOrganization(user_id=user.id, organization_id=org.id, role="planer"))
        convoy = Convoy(
            name=f"Verband {marker}", owner_id=user.id, organization_id=org.id,
            start_point=from_shape(Point(PUNKTE[0]["lon"], PUNKTE[0]["lat"]), srid=4326),
            end_point=from_shape(Point(PUNKTE[1]["lon"], PUNKTE[1]["lat"]), srid=4326),
            speed_urban_kmh=40, speed_rural_kmh=65,
        )
        db.add(convoy)
        await db.commit()
        ids = SimpleNamespace(user_id=user.id, org_id=org.id, convoy_id=convoy.id)

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=ids.user_id, is_superadmin=False)
    app.dependency_overrides[get_token_data] = lambda: SimpleNamespace(user_id=str(ids.user_id), is_demo=False)
    yield ids
    app.dependency_overrides.clear()
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Route).where(Route.convoy_id == ids.convoy_id))
        await db.execute(delete(Convoy).where(Convoy.id == ids.convoy_id))
        await db.execute(delete(UserOrganization).where(UserOrganization.organization_id == ids.org_id))
        await db.execute(delete(Organization).where(Organization.id == ids.org_id))
        await db.execute(delete(User).where(User.id == ids.user_id))
        await db.commit()


async def test_abbruch_nach_der_frist_sagt_das(verband, monkeypatch):
    monkeypatch.setattr(settings, "graphhopper_timeout_s", 180.0)
    monkeypatch.setattr(routing_svc, "httpx", _graphhopper(httpx.ReadTimeout("zu lang"), [], []))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(f"/api/convoys/{verband.convoy_id}/calculate-route")
    assert r.status_code == 504, r.text
    detail = r.json()["detail"]
    assert "180 s" in detail
    assert "GRAPHHOPPER_TIMEOUT_S" in detail
    assert "nicht verfügbar" not in detail


async def test_nicht_erreichbar_bleibt_nicht_verfuegbar(verband, monkeypatch):
    monkeypatch.setattr(routing_svc, "httpx", _graphhopper(httpx.ConnectError("weg"), [], []))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(f"/api/convoys/{verband.convoy_id}/calculate-route")
    assert r.status_code == 502, r.text
    assert r.json()["detail"] == "Routing-Dienst nicht verfügbar"
