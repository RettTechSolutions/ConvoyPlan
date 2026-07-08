"""Tests für den Open-Data-Verkehrsdatenservice (MobiData-BW-Stil GeoJSON)."""
import httpx
import pytest

from app.config import settings
from app.services import opendata_traffic as od
from app.services.opendata_traffic import _to_feature, features_along_route, features_around


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    od._cache = {"features": None, "fetched_at": 0.0}
    monkeypatch.setattr(settings, "opendata_traffic_enabled", True)
    monkeypatch.setattr(settings, "opendata_traffic_feeds", "https://example.org/roadworks.json")
    yield


# ── Normalisierung ───────────────────────────────────────────────────


def test_to_feature_roadworks():
    raw = {
        "geometry": {"type": "LineString", "coordinates": [[9.0, 48.5], [9.01, 48.51]]},
        "properties": {"type": "CONSTRUCTION", "street": "K1077", "description": "Erdlager",
                       "reference": "MobiData BW", "id": "abc"},
    }
    f = _to_feature(raw, "example.org")
    assert f["properties"]["source"] == "opendata"
    assert f["properties"]["provider"] == "MobiData BW"
    assert f["properties"]["service"] == "roadworks"
    assert f["properties"]["isBlocked"] == "false"
    assert f["properties"]["title"] == "K1077"


def test_to_feature_closure_detected():
    raw = {
        "geometry": {"type": "Point", "coordinates": [9.0, 48.5]},
        "properties": {"type": "CLOSURE", "street": "B14"},
    }
    f = _to_feature(raw, "example.org")
    assert f["properties"]["service"] == "closure"
    assert f["properties"]["isBlocked"] == "true"


def test_to_feature_requires_geometry():
    assert _to_feature({"properties": {"street": "x"}}, "p") is None


# ── Zeitfilter ───────────────────────────────────────────────────────


def test_expired_events_are_dropped():
    assert od._is_active({"endtime": "2000-01-01T00:00:00+00:00"}, od.datetime.now(od.timezone.utc)) is False


def test_active_and_open_ended_events_kept():
    now = od.datetime.now(od.timezone.utc)
    assert od._is_active({"endtime": "2999-01-01T00:00:00+00:00"}, now) is True
    assert od._is_active({}, now) is True  # kein Enddatum → behalten


# ── HTTP + Filter ────────────────────────────────────────────────────


class _FeedClient:
    payload: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    async def get(self, url):
        return httpx.Response(200, json=_FeedClient.payload, request=httpx.Request("GET", url))


def _payload(*features):
    return {"type": "FeatureCollection", "features": list(features)}


async def test_features_around_filters_by_radius(monkeypatch):
    _FeedClient.payload = _payload(
        {"geometry": {"type": "Point", "coordinates": [9.00, 48.50]},
         "properties": {"type": "CONSTRUCTION", "street": "nah", "id": "1",
                        "endtime": "2999-01-01T00:00:00+00:00"}},
        {"geometry": {"type": "Point", "coordinates": [13.40, 52.50]},
         "properties": {"type": "CONSTRUCTION", "street": "fern", "id": "2",
                        "endtime": "2999-01-01T00:00:00+00:00"}},
    )
    monkeypatch.setattr(od.httpx, "AsyncClient", _FeedClient)
    out = await features_around(48.50, 9.00, radius_m=2000)
    assert {f["properties"]["title"] for f in out} == {"nah"}


async def test_features_along_route_corridor(monkeypatch):
    _FeedClient.payload = _payload(
        {"geometry": {"type": "Point", "coordinates": [11.05, 48.05]},
         "properties": {"type": "CONSTRUCTION", "street": "auf-route", "id": "1"}},
        {"geometry": {"type": "Point", "coordinates": [9.0, 53.0]},
         "properties": {"type": "CONSTRUCTION", "street": "weit-weg", "id": "2"}},
    )
    monkeypatch.setattr(od.httpx, "AsyncClient", _FeedClient)
    out = await features_along_route([(11.0, 48.0), (11.1, 48.1)], corridor_m=8000)
    assert {f["properties"]["title"] for f in out} == {"auf-route"}


async def test_disabled_returns_empty(monkeypatch):
    monkeypatch.setattr(settings, "opendata_traffic_enabled", False)
    out = await features_around(48.5, 9.0, 5000)
    assert out == []
