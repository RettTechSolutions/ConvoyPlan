"""Tests für den Autobahn-API-Service (zweite Verkehrsdatenquelle)."""
import httpx
import pytest

from app.services import autobahn as autobahn_svc
from app.services.autobahn import (
    _item_to_feature,
    _point_coord,
    features_along_route,
    features_around,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Modul-Cache vor jedem Test leeren (Cache ist Modul-State)."""
    autobahn_svc._cache = {"features": None, "fetched_at": 0.0}
    autobahn_svc._last_check = {"status": "unknown", "latency_ms": None, "checked_at": None}
    yield


# ── Item → Feature ───────────────────────────────────────────────────


def test_item_to_feature_uses_geometry():
    item = {
        "_service": "roadworks",
        "title": "A1 Baustelle",
        "isBlocked": "false",
        "geometry": {"type": "LineString", "coordinates": [[6.95, 49.28], [6.96, 49.29]]},
        "coordinate": {"lat": 49.28, "long": 6.95},
    }
    f = _item_to_feature(item)
    assert f["geometry"]["type"] == "LineString"
    assert f["geometry"]["coordinates"] == [[6.95, 49.28], [6.96, 49.29]]
    assert f["properties"]["source"] == "autobahn"
    assert f["properties"]["service"] == "roadworks"
    assert f["properties"]["title"] == "A1 Baustelle"


def test_item_to_feature_falls_back_to_coordinate():
    item = {"_service": "warning", "coordinate": {"lat": 50.1, "long": 8.2}}
    f = _item_to_feature(item)
    assert f["geometry"] == {"type": "Point", "coordinates": [8.2, 50.1]}


def test_item_to_feature_returns_none_without_position():
    assert _item_to_feature({"_service": "closure", "title": "x"}) is None


def test_point_coord_from_point_string():
    assert _point_coord({"point": "49.5,7.1"}) == (49.5, 7.1)


# ── Filter: Radius ───────────────────────────────────────────────────


class _RoadsClient:
    """httpx.AsyncClient-Ersatz mit konfigurierbaren Antworten je URL."""

    roads: list[str] = ["A1"]
    service_items: dict[str, list] = {}
    fail_on: set[str] = set()
    calls: list[str] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        _RoadsClient.calls.append(url)
        if url in _RoadsClient.fail_on:
            raise httpx.ConnectTimeout("boom")
        if url.rstrip("/").endswith("/o/autobahn"):
            return httpx.Response(200, json={"roads": _RoadsClient.roads},
                                  request=httpx.Request("GET", url))
        svc = url.rsplit("/", 1)[-1]
        return httpx.Response(200, json={svc: _RoadsClient.service_items.get(svc, [])},
                              request=httpx.Request("GET", url))


def _configure(monkeypatch, roads, items, fail_on=None):
    _RoadsClient.roads = roads
    _RoadsClient.service_items = items
    _RoadsClient.fail_on = fail_on or set()
    _RoadsClient.calls = []
    monkeypatch.setattr(autobahn_svc.httpx, "AsyncClient", _RoadsClient)


async def test_features_around_filters_by_radius(monkeypatch):
    _configure(monkeypatch, ["A1"], {
        "roadworks": [
            {"identifier": "near", "title": "nah", "coordinate": {"lat": 49.2810, "long": 6.9560}},
            {"identifier": "far", "title": "fern", "coordinate": {"lat": 52.5, "long": 13.4}},
        ],
        "warning": [],
        "closure": [],
    })
    out = await features_around(49.2810, 6.9560, radius_m=2000)
    titles = {f["properties"]["title"] for f in out}
    assert titles == {"nah"}


async def test_features_dedup_by_identifier(monkeypatch):
    # Dieselbe Meldung taucht auf zwei Autobahnen auf → nur einmal.
    dup = {"identifier": "shared", "title": "dup", "coordinate": {"lat": 49.28, "long": 6.95}}
    _configure(monkeypatch, ["A1", "A620"], {
        "roadworks": [dup], "warning": [], "closure": [],
    })
    out = await features_around(49.28, 6.95, radius_m=3000)
    assert len(out) == 1


async def test_features_along_route_corridor(monkeypatch):
    _configure(monkeypatch, ["A1"], {
        "roadworks": [
            {"identifier": "on", "title": "auf-route", "coordinate": {"lat": 48.05, "long": 11.05}},
            {"identifier": "off", "title": "weit-weg", "coordinate": {"lat": 53.0, "long": 9.0}},
        ],
        "warning": [], "closure": [],
    })
    # Route in GeoJSON-Reihenfolge [lon, lat]
    coords = [(11.0, 48.0), (11.1, 48.1)]
    out = await features_along_route(coords, corridor_m=8000)
    titles = {f["properties"]["title"] for f in out}
    assert titles == {"auf-route"}


# ── Cache & Fehlertoleranz ───────────────────────────────────────────


async def test_national_fetch_is_cached(monkeypatch):
    _configure(monkeypatch, ["A1"], {"roadworks": [], "warning": [], "closure": []})
    await features_around(49.0, 7.0, 1000)
    first_calls = len(_RoadsClient.calls)
    assert first_calls > 0
    await features_around(50.0, 8.0, 1000)
    # Zweiter Aufruf nutzt den Cache — keine neuen HTTP-Requests.
    assert len(_RoadsClient.calls) == first_calls


async def test_per_road_failure_is_tolerated(monkeypatch):
    items = {
        "roadworks": [{"identifier": "ok", "title": "ok", "coordinate": {"lat": 49.28, "long": 6.95}}],
        "warning": [], "closure": [],
    }
    _configure(monkeypatch, ["A1", "A2"], items,
               fail_on={"https://verkehr.autobahn.de/o/autobahn/A2/services/roadworks"})
    out = await features_around(49.28, 6.95, radius_m=3000)
    # A1 liefert weiterhin Daten, A2-Fehler wird verschluckt.
    assert len(out) == 1


async def test_stale_cache_survives_refresh_failure(monkeypatch):
    _configure(monkeypatch, ["A1"], {
        "roadworks": [{"identifier": "x", "title": "x", "coordinate": {"lat": 49.28, "long": 6.95}}],
        "warning": [], "closure": [],
    })
    await features_around(49.28, 6.95, 3000)  # Cache füllen
    # TTL künstlich ablaufen lassen und die Roads-Liste scheitern lassen.
    autobahn_svc._cache["fetched_at"] = 0.0
    _RoadsClient.fail_on = {"https://verkehr.autobahn.de/o/autobahn/"}
    out = await features_around(49.28, 6.95, 3000)
    # Alter Cache bleibt erhalten statt zu leeren.
    assert len(out) == 1
