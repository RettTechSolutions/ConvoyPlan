"""Fähren: Die Überfahrt ist Reisezeit, keine Lenkzeit.

Gemeldet: München → Shkodër über Bari–Durrës. Ein Technischer Halt lag mitten
in der Adria, die Tagesruhe kurz vor dem Fährhafen, eine Lenkpause kurz nach
der Ankunft — die Strecke über See zählte als Landstraße. Die Zusagen:

- die Fährabschnitte kommen aus GraphHoppers ``road_environment``, ihre Dauer
  aus dessen ``time``; passt die nicht zu einer Fähre, wird geschätzt und das
  gesagt;
- die Meter auf See zählen nicht zur Fahrzeit des Konvois, die Überfahrt aber
  zur Reisezeit — Zeitplan und Ankunft stimmen;
- kein empfohlener Halt liegt auf See; was dort fällig wäre, liegt am Hafen;
- die Überfahrt ist ein Halt: ab 45 min Lenkpause, ab 9 h Tagesruhe;
- eine Route von vor der Erkennung (``None``) rechnet wie bisher.
"""
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from geoalchemy2.shape import from_shape
from httpx import ASGITransport, AsyncClient
from shapely.geometry import Point
from sqlalchemy import delete, select

from app.api.deps import get_current_user, get_token_data
from app.database import AsyncSessionLocal, engine
from app.main import app
from app.models.convoy import Convoy
from app.models.organization import Organization, UserOrganization
from app.models.route import Route
from app.models.user import User
from app.services import faehre
from app.services import routing as routing_svc
from app.services.fuel import halteplan

# Gerade Strecke nach Osten, 100 Abschnitte zu je ~8,4 km; Fähre von Punkt 40 bis 65.
COORDS = [[12.0 + i * 0.1, 41.0] for i in range(101)]
VON, BIS = 40, 65
NEUN_H_MS = int(9.5 * 3600 * 1000)
ENV = [[0, VON, "road"], [VON, BIS, "ferry"], [BIS, 100, "road"]]
ZEIT = [[0, VON, 4 * 3600 * 1000], [VON, BIS, NEUN_H_MS], [BIS, 100, 4 * 3600 * 1000]]


# ── Abschnitte ───────────────────────────────────────────────────────────────


def test_abschnitt_aus_road_environment_und_time():
    [f] = faehre.abschnitte(ENV, ZEIT, COORDS)
    cum = faehre._kumuliert(COORDS)
    assert f["von_m"] == round(cum[VON]) and f["bis_m"] == round(cum[BIS])
    assert f["km"] == round(cum[VON] / 1000, 1)
    assert f["dauer_s"] == pytest.approx(9.5 * 3600, abs=1)
    assert (f["lat"], f["lon"]) == (COORDS[VON][1], COORDS[VON][0])
    assert (f["ziel_lat"], f["ziel_lon"]) == (COORDS[BIS][1], COORDS[BIS][0])
    assert f["geschaetzt"] is False


def test_ohne_faehre_keine_abschnitte():
    assert faehre.abschnitte([[0, 100, "road"]], ZEIT, COORDS) == []
    assert faehre.abschnitte([], [], COORDS) == []


def test_aneinanderstossende_faehrkanten_sind_eine_ueberfahrt():
    env = [[0, VON, "road"], [VON, 50, "ferry"], [50, BIS, "FERRY"], [BIS, 100, "road"]]
    assert len(faehre.abschnitte(env, ZEIT, COORDS)) == 1


@pytest.mark.parametrize("zeit", [[], [[VON, BIS, 60_000]]], ids=["ohne Zeit", "zu schnell"])
def test_unplausible_dauer_wird_geschaetzt(zeit):
    [f] = faehre.abschnitte(ENV, zeit, COORDS)
    assert f["geschaetzt"] is True
    assert f["dauer_s"] == pytest.approx(f["laenge_km"] / faehre.ERSATZ_KMH * 3600, rel=0.01)


# ── Zeitachse ────────────────────────────────────────────────────────────────

F = {"von_m": 100_000, "bis_m": 300_000, "dauer_s": 10 * 3600}


def test_auf_see_vergeht_keine_lenkzeit():
    achse = faehre.Zeitachse(500_000, 3 * 3600, [F])  # 300 km Land in 3 h
    assert achse.lenkzeit(100_000) == pytest.approx(3600)
    assert achse.lenkzeit(300_000) == pytest.approx(3600)
    assert achse.lenkzeit(500_000) == pytest.approx(3 * 3600)


def test_ein_halt_auf_see_liegt_am_hafen_davor():
    achse = faehre.Zeitachse(500_000, 3 * 3600, [F])
    assert achse.meter_bei_lenkzeit(3600) == pytest.approx(100_000)
    assert achse.meter_bei_lenkzeit(1.5 * 3600) == pytest.approx(350_000)


def test_reisezeit_enthaelt_die_ueberfahrt():
    achse = faehre.Zeitachse(500_000, 3 * 3600, [F])
    assert achse.reisezeit(500_000) == pytest.approx(13 * 3600)
    assert achse.reisezeit(200_000) == pytest.approx(3600 + 5 * 3600)
    assert achse.abschnittszeiten([50_000, 400_000, 500_000]) == [1800, 1800 + 10 * 3600 + 3600, 3600]


def test_ohne_faehre_linear_wie_bisher():
    achse = faehre.Zeitachse(500_000, 5 * 3600, [])
    assert achse.meter_bei_lenkzeit(3600) == pytest.approx(100_000)
    assert achse.reisezeit(250_000) == pytest.approx(2.5 * 3600)


# ── Halteempfehlung ──────────────────────────────────────────────────────────


def _halte(lenkzeit_h, faehren):
    return halteplan(500, lenkzeit_h * 3600, [], 3, [], faehren)[0]


def test_kein_halt_auf_see():
    # 300 km Land in 6 h: TH nach 2 h fiele genau auf die Fähre.
    for h in _halte(6, [{**F, "dauer_s": 30 * 60}]):
        assert not (100 < h["stop_km"] < 300), h


def test_lange_ueberfahrt_ist_tagesruhe():
    """8 h vor der Fähre, 9,5 h Überfahrt, danach weiter: keine Tagesruhe an Land."""
    f = {"von_m": 400_000, "bis_m": 600_000, "dauer_s": int(9.5 * 3600)}
    halte = halteplan(900, 12 * 3600, [], 3, [], [f])[0]
    assert "daily_rest" not in [h["kind"] for h in halte]


def test_kurze_ueberfahrt_ist_nur_lenkpause():
    f = {"von_m": 400_000, "bis_m": 450_000, "dauer_s": 2 * 3600}
    halte = halteplan(900, 12 * 3600, [], 3, [], [f])[0]
    assert "daily_rest" in [h["kind"] for h in halte]
    # Die Lenkpause steckt in der Überfahrt: keine kurz davor oder danach.
    assert not [h for h in halte if h["kind"] == "break" and 330 < h["stop_km"] < 520]


def test_ohne_faehre_unveraendert():
    assert _halte(6, []) == halteplan(500, 6 * 3600, [], 3, [])[0]


def test_fahrzeit_ohne_see_meter():
    rc = [[0, 100, "primary"]]
    mit = routing_svc.convoy_duration_s(840_000, COORDS, rc, 40, 70)
    ohne = routing_svc.convoy_duration_s(840_000, COORDS, rc, 40, 70, ohne=[(VON, BIS)])
    assert ohne == pytest.approx(mit * 75 / 100, rel=0.01)


# ── Durch die App ────────────────────────────────────────────────────────────


def _graphhopper(gesendet: list, details: dict):
    class _Resp:
        status_code = 200
        is_success = True

        def json(self):
            return {"paths": [{
                "distance": 840_000.0, "time": 17 * 3600 * 1000,
                "points": {"type": "LineString", "coordinates": COORDS},
                "details": details, "instructions": [],
            }]}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            gesendet.append(json)
            return _Resp()

    return SimpleNamespace(AsyncClient=_Client)


@pytest.fixture(autouse=True)
async def reset_db_engine():
    yield
    await engine.dispose()


@pytest.fixture
async def verband():
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(email=f"fae-{marker}@test.invalid", hashed_password="x", is_active=True)
        db.add(user)
        await db.flush()
        org = Organization(name=f"Org {marker}", slug=f"org-{marker}", owner_id=user.id)
        db.add(org)
        await db.flush()
        db.add(UserOrganization(user_id=user.id, organization_id=org.id, role="planer"))
        convoy = Convoy(
            name=f"Verband {marker}", owner_id=user.id, organization_id=org.id,
            start_point=from_shape(Point(*COORDS[0]), srid=4326),
            end_point=from_shape(Point(*COORDS[-1]), srid=4326),
            speed_urban_kmh=40, speed_rural_kmh=70, start_time=datetime(2026, 11, 7, 6, 0),
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


DETAILS = {"road_class": [[0, 100, "primary"]], "road_environment": ENV, "time": ZEIT}


async def test_berechnung_mit_faehre(verband, monkeypatch):
    gesendet: list = []
    monkeypatch.setattr(routing_svc, "httpx", _graphhopper(gesendet, DETAILS))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(f"/api/convoys/{verband.convoy_id}/calculate-route")
        assert r.status_code == 200, r.text
        geladen = (await client.get(f"/api/convoys/{verband.convoy_id}/route")).json()

    assert {"road_environment", "time"} <= set(gesendet[0]["details"])
    body = r.json()
    [f] = body["faehren"]
    assert f["dauer_s"] == pytest.approx(9.5 * 3600, abs=1)
    assert geladen["faehren"] == body["faehren"]

    # Lenkzeit nur an Land (75 % der Strecke bei 70 km/h), Reisezeit mit Überfahrt.
    land_km = (faehre._kumuliert(COORDS)[-1] - (f["bis_m"] - f["von_m"])) / 1000
    assert body["duration_s"] == pytest.approx(land_km / 70 * 3600 + 9.5 * 3600, rel=0.01)
    # Ankunft = Abmarsch + Reisezeit (keine Haltezeiten an Wegpunkten).
    ankunft = datetime.fromisoformat(body["planned_arrival"])
    assert (ankunft - datetime(2026, 11, 7, 6, 0)).total_seconds() == pytest.approx(body["duration_s"], abs=2)

    for analyse in (body["fuel_analysis"], geladen["fuel_analysis"]):
        for h in analyse["duration_halts"]:
            assert not (f["von_m"] / 1000 < h["stop_km"] < f["bis_m"] / 1000), h
        assert "daily_rest" not in [h["kind"] for h in analyse["duration_halts"]]

    async with AsyncSessionLocal() as db:
        route = (await db.execute(select(Route).where(Route.convoy_id == verband.convoy_id))).scalar_one()
    assert route.faehren == body["faehren"]


async def test_graph_ohne_road_environment_rechnet_wie_bisher(verband, monkeypatch):
    gesendet: list = []
    ohne = _graphhopper(gesendet, {"road_class": [[0, 100, "primary"]]})

    class _Ablehnend(ohne.AsyncClient):
        async def post(self, url, json):
            if "road_environment" in json["details"]:
                gesendet.append(json)
                return SimpleNamespace(
                    status_code=400, is_success=False, text="",
                    json=lambda: {"message": "Cannot find encoded value road_environment"},
                )
            return await super().post(url, json)

    monkeypatch.setattr(routing_svc, "httpx", SimpleNamespace(AsyncClient=_Ablehnend))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(f"/api/convoys/{verband.convoy_id}/calculate-route")
    assert r.status_code == 200, r.text
    assert r.json()["faehren"] is None
    assert len(gesendet) == 2 and "road_environment" not in gesendet[1]["details"]
