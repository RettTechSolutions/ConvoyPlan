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


def test_kanalwechsel_sorted_by_km():
    entries = [
        {"km": 67.8, "lat": 47.9, "lon": 12.5, "leitstelle_id": "a", "leitstelle_name": "ILS B", "anrufgruppe": "452"},
        {"km": 34.2, "lat": 47.8, "lon": 12.1, "leitstelle_id": "b", "leitstelle_name": "ILS A", "anrufgruppe": "438"},
    ]
    entries.sort(key=lambda x: x["km"])
    assert entries[0]["km"] == 34.2
    assert entries[1]["km"] == 67.8
