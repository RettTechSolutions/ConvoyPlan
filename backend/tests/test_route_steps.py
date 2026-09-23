"""Fahrhinweise für die Verfolgung: der Meter auf der Linie, an dem ein Manöver liegt.

Die Companion-App projiziert den eigenen Standort auf die ausgelieferte Linie
und vergleicht den Meter mit dem des Hinweises. Beide Zahlen müssen deshalb
auf dieselbe Weise entstehen — Haversine über die Stützpunkte —, sonst kündigt
die App ein Manöver um die Differenz zu früh oder zu spät an.
"""
import uuid
from types import SimpleNamespace

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import LineString
from sqlalchemy import delete

from app.api.routes import track as track_module
from app.database import AsyncSessionLocal, engine
from app.models.convoy import Convoy
from app.models.organization import Organization, UserOrganization
from app.models.route import Route
from app.models.user import User
from app.services import route_steps
from app.services import routing as routing_svc
from app.services.fuel import haversine_m

# Drei Stützpunkte, grob einen und zwei Kilometer auseinander.
COORDS = [[9.0, 48.0], [9.0, 48.01], [9.02, 48.01]]
ERSTES = haversine_m(9.0, 48.0, 9.0, 48.01)
ZWEITES = haversine_m(9.0, 48.01, 9.02, 48.01)


# ── Rechnung ohne Datenbank ──────────────────────────────────────────────────


def test_meter_laufen_ueber_die_stuetzpunkte_auf():
    along = route_steps.cumulative_m(COORDS)

    assert along[0] == 0.0
    assert along[1] == pytest.approx(ERSTES)
    assert along[2] == pytest.approx(ERSTES + ZWEITES)
    assert route_steps.cumulative_m([]) == []


def test_der_meter_kommt_aus_dem_intervall_von_graphhopper():
    along = route_steps.cumulative_m(COORDS)

    assert route_steps.instruction_m([1, 2], along) == round(ERSTES, 1)
    assert route_steps.instruction_m([0, 1], along) == 0.0


@pytest.mark.parametrize("interval", [None, [], [7, 8], [-1, 0], ["1", 2], [True, 1]])
def test_ohne_passendes_intervall_gibt_es_keinen_meter(interval):
    # Lieber keinen Meter als einen erfundenen.
    assert route_steps.instruction_m(interval, route_steps.cumulative_m(COORDS)) is None


def test_compact_instructions_schreibt_den_meter_mit():
    raw = [
        {"sign": 0, "text": "Losfahren", "distance": 1111.9, "interval": [0, 1]},
        {"sign": 2, "text": "Rechts abbiegen", "distance": 1489.1, "interval": [1, 2],
         "street_name": "Ringstraße"},
        {"sign": 4, "text": "Ziel erreicht!", "distance": 0, "interval": [2, 2]},
    ]

    out = routing_svc.compact_instructions(raw, COORDS)

    assert [i["m"] for i in out] == [0.0, round(ERSTES, 1), round(ERSTES + ZWEITES, 1)]
    # Das Intervall selbst wird nicht gespeichert.
    assert all("interval" not in i for i in out)


def test_compact_instructions_ohne_geometrie_bleibt_beim_alten():
    out = routing_svc.compact_instructions([{"sign": 2, "text": "Rechts", "distance": 10, "interval": [0, 1]}])

    assert "m" not in out[0]


def test_track_steps_nimmt_den_gespeicherten_meter():
    steps = route_steps.track_steps(
        [
            {"sign": 0, "text": "Losfahren", "distance_m": 1111.9, "m": 0.0, "street_name": "Hauptstraße"},
            {"sign": 6, "text": "", "distance_m": 10.0, "m": 1112.0, "street_ref": "B 27", "exit_number": 2},
        ],
        COORDS,
    )

    assert steps == [
        {"m": 0.0, "sign": 0, "text": "Losfahren", "street_name": "Hauptstraße", "exit_number": None},
        # Leerer Text wird zu None; ohne Namen tritt die Nummer an seine Stelle.
        {"m": 1112.0, "sign": 6, "text": None, "street_name": "B 27", "exit_number": 2},
    ]


def test_alte_hinweise_ohne_meter_werden_auf_die_linie_gestreckt():
    # Vor dieser Änderung berechnet: nur die Teilstrecken. Summiert ergeben
    # sie hier die halbe Linienlänge — gestreckt landet das Ziel am Ende.
    halbe = (ERSTES + ZWEITES) / 2
    steps = route_steps.track_steps(
        [
            {"sign": 0, "text": "Losfahren", "distance_m": halbe / 2},
            {"sign": 2, "text": "Rechts", "distance_m": halbe / 2},
            {"sign": 4, "text": "Ziel", "distance_m": 0},
        ],
        COORDS,
    )

    assert [s["m"] for s in steps] == pytest.approx([0.0, (ERSTES + ZWEITES) / 2, ERSTES + ZWEITES], abs=0.1)


def test_ein_eintrag_ohne_meter_schaltet_alle_auf_den_rueckfall():
    steps = route_steps.track_steps(
        [
            {"sign": 0, "text": "a", "distance_m": 100.0, "m": 0.0},
            {"sign": 2, "text": "b", "distance_m": 100.0},
        ],
        COORDS,
    )

    assert [s["m"] for s in steps] == sorted(s["m"] for s in steps)


def test_ohne_hinweise_oder_linie_gibt_es_keine():
    assert route_steps.track_steps(None, COORDS) == []
    assert route_steps.track_steps([], COORDS) == []
    assert route_steps.track_steps([{"sign": 2, "m": 0.0}], [[9.0, 48.0]]) == []


# ── Über den Draht: was /api/track/{slug} ausliefert ──────────────────────────


@pytest.fixture(autouse=True)
async def reset_db_engine():
    """Verbindungspool nach jedem Test schließen (siehe test_mannschaftsstaerke)."""
    yield
    await engine.dispose()


@pytest.fixture
async def verband():
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(email=f"rs-{marker}@test.invalid", hashed_password="x", is_active=True)
        db.add(user)
        await db.flush()
        org = Organization(name=f"Org {marker}", slug=f"org-{marker}", owner_id=user.id)
        db.add(org)
        await db.flush()
        db.add(UserOrganization(user_id=user.id, organization_id=org.id, role="planer"))
        convoy = Convoy(name=f"Verband {marker}", owner_id=user.id, organization_id=org.id)
        db.add(convoy)
        await db.commit()
        ids = SimpleNamespace(user_id=user.id, org_id=org.id, convoy_id=convoy.id)

    yield ids

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Route).where(Route.convoy_id == ids.convoy_id))
        await db.execute(delete(Convoy).where(Convoy.id == ids.convoy_id))
        await db.execute(delete(UserOrganization).where(UserOrganization.organization_id == ids.org_id))
        await db.execute(delete(Organization).where(Organization.id == ids.org_id))
        await db.execute(delete(User).where(User.id == ids.user_id))
        await db.commit()


async def _route(ids, instructions):
    async with AsyncSessionLocal() as db:
        db.add(Route(
            convoy_id=ids.convoy_id,
            geometry=from_shape(LineString(COORDS), srid=4326),
            distance_m=2600,
            instructions=instructions,
        ))
        await db.commit()


async def test_tracking_liefert_die_hinweise_mit_meter_aus(verband):
    await _route(verband, routing_svc.compact_instructions(
        [
            {"sign": 0, "text": "Losfahren", "distance": 1111.9, "interval": [0, 1], "street_name": "Hauptstraße"},
            {"sign": 2, "text": "Rechts abbiegen auf Ringstraße", "distance": 1489.1, "interval": [1, 2],
             "street_name": "Ringstraße"},
            {"sign": 4, "text": "Ziel erreicht!", "distance": 0, "interval": [2, 2]},
        ],
        COORDS,
    ))

    async with AsyncSessionLocal() as db:
        payload = await track_module._build_payload(verband.convoy_id, db)

    body = payload.model_dump()
    assert [s["sign"] for s in body["route_steps"]] == [0, 2, 4]
    rechts = body["route_steps"][1]
    assert rechts["m"] == round(ERSTES, 1)
    assert rechts["text"] == "Rechts abbiegen auf Ringstraße"
    assert rechts["street_name"] == "Ringstraße"
    # Derselbe Meter, den ein Empfänger aus der ausgelieferten Linie misst.
    linie = body["geojson"]["coordinates"]
    assert rechts["m"] == pytest.approx(route_steps.cumulative_m(linie)[1], abs=0.1)


async def test_importierte_route_liefert_keine_hinweise(verband):
    await _route(verband, None)

    async with AsyncSessionLocal() as db:
        payload = await track_module._build_payload(verband.convoy_id, db)

    assert payload.route_steps == []


async def test_ohne_route_gibt_es_keine_hinweise(verband):
    async with AsyncSessionLocal() as db:
        payload = await track_module._build_payload(verband.convoy_id, db)

    assert payload.route_steps == []
