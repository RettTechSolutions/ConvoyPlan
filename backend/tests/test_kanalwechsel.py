import uuid
import pytest


def test_kanalwechsel_entry_schema():
    from app.schemas.route import KanalwechselEntry
    entry = KanalwechselEntry(
        km=34.2, lat=47.856, lon=12.103,
        leitstelle_id=str(uuid.uuid4()),
        leitstelle_name="ILS Rosenheim",
        anrufgruppe="438",
    )
    assert entry.km == 34.2
    assert entry.leitstelle_name == "ILS Rosenheim"


def test_route_response_includes_kanalwechsel():
    from app.schemas.route import RouteResponse, KanalwechselEntry
    r = RouteResponse(
        id=uuid.uuid4(),
        convoy_id=uuid.uuid4(),
        distance_m=50000,
        duration_s=3600,
        routing_params=None,
        geojson=None,
        kanalwechsel=[
            KanalwechselEntry(
                km=25.0, lat=48.0, lon=11.0,
                leitstelle_id=str(uuid.uuid4()),
                leitstelle_name="ILS München",
                anrufgruppe="468",
            )
        ],
    )
    assert len(r.kanalwechsel) == 1
    assert r.kanalwechsel[0].anrufgruppe == "468"


@pytest.mark.asyncio
async def test_compute_kanalwechsel_skips_empty_geometries():
    """POINT EMPTY / leere MultiPoint-Einträge von PostGIS dürfen keinen
    ValueError beim Entpacken auslösen (Produktions-500 bei calculate-route)."""
    from types import SimpleNamespace
    from shapely.geometry import LineString
    from app.api.routes.routing import _compute_kanalwechsel

    rows = [
        # POINT EMPTY → coordinates: []
        SimpleNamespace(id=uuid.uuid4(), name="ILS Leer", anrufgruppe="400",
                        crossing_geojson='{"type":"Point","coordinates":[]}'),
        # MultiPoint mit einem leeren und einem gültigen (3D-)Punkt
        SimpleNamespace(id=uuid.uuid4(), name="ILS Gültig", anrufgruppe="438",
                        crossing_geojson='{"type":"MultiPoint","coordinates":[[],[11.5,48.25,0]]}'),
    ]

    class FakeResult:
        def __init__(self, rows=None, scalar=None):
            self._rows, self._scalar = rows, scalar
        def all(self):
            return self._rows
        def scalar(self):
            return self._scalar

    class FakeDB:
        def __init__(self, results):
            self._results = list(results)
        async def execute(self, *_a, **_k):
            return self._results.pop(0)

    # 1. Query: Leitstellen-Schnittpunkte, 2. Query: ST_LineLocatePoint-Fraktion
    db = FakeDB([FakeResult(rows=rows), FakeResult(scalar=0.5)])
    line = LineString([(11.0, 48.0), (12.0, 49.0)])

    entries = await _compute_kanalwechsel(db, line, distance_m=100_000)

    assert len(entries) == 1
    assert entries[0]["leitstelle_name"] == "ILS Gültig"
    assert entries[0]["km"] == 50.0
    assert entries[0]["lat"] == 48.25
    assert entries[0]["lon"] == 11.5


def test_kanalwechsel_sorted_by_km():
    entries = [
        {"km": 67.8, "lat": 47.9, "lon": 12.5, "leitstelle_id": "a", "leitstelle_name": "ILS B", "anrufgruppe": "452"},
        {"km": 34.2, "lat": 47.8, "lon": 12.1, "leitstelle_id": "b", "leitstelle_name": "ILS A", "anrufgruppe": "438"},
    ]
    entries.sort(key=lambda x: x["km"])
    assert entries[0]["km"] == 34.2
    assert entries[1]["km"] == 67.8
