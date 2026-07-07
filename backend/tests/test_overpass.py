"""Tests für den Overpass-Service (Sperrungen entlang der Route)."""
import httpx
import pytest

from app.services import overpass as overpass_svc
from app.services.overpass import (
    _closures_query,
    _sample_route,
    get_closures_along_route,
)


# ── _sample_route ────────────────────────────────────────────────────


def test_sample_route_keeps_short_routes():
    coords = [(48.0, 11.0), (48.1, 11.1)]
    assert _sample_route(coords) == coords


def test_sample_route_keeps_endpoints():
    # 500 Punkte entlang eines Längengrads (~111 km)
    coords = [(48.0 + i * 0.002, 11.0) for i in range(500)]
    sampled = _sample_route(coords, max_points=150)
    assert sampled[0] == coords[0]
    assert sampled[-1] == coords[-1]
    assert len(sampled) <= 152


def test_sample_route_reduces_dense_polyline():
    # 2000 dicht liegende Punkte (~22 km) müssen deutlich reduziert werden
    coords = [(48.0 + i * 0.0001, 11.0) for i in range(2000)]
    sampled = _sample_route(coords, max_points=150)
    assert len(sampled) < 100
    assert sampled[0] == coords[0]
    assert sampled[-1] == coords[-1]


# ── Query-Bau ────────────────────────────────────────────────────────


def test_closures_query_contains_filters():
    q = _closures_query("around:2000,48.00000,11.00000")
    assert 'way["highway"="construction"](around:2000,48.00000,11.00000);' in q
    assert 'node["hazard"="construction"](around:2000,48.00000,11.00000);' in q
    assert "out geom;" in q


# ── get_closures_along_route ─────────────────────────────────────────


class _MockClient:
    """httpx.AsyncClient-Ersatz, der die Query aufzeichnet."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data=None, headers=None):
        _MockClient.last_query = data["data"]
        return httpx.Response(
            200,
            json={"elements": [
                {"type": "node", "id": 1, "lat": 48.05, "lon": 11.05,
                 "tags": {"highway": "construction"}},
            ]},
            request=httpx.Request("POST", url),
        )


@pytest.mark.asyncio
async def test_get_closures_along_route_builds_polyline_query(monkeypatch):
    monkeypatch.setattr(overpass_svc.httpx, "AsyncClient", _MockClient)
    # GeoJSON-Reihenfolge [lon, lat]
    coords = [(11.0, 48.0), (11.1, 48.1), (11.2, 48.2)]
    result = await get_closures_along_route(coords, corridor_m=1500)

    # Query nutzt Polyline-around mit lat,lon-Reihenfolge und Korridor
    assert "around:1500,48.00000,11.00000" in _MockClient.last_query
    assert "48.20000,11.20000" in _MockClient.last_query

    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 1
    assert result["features"][0]["geometry"]["type"] == "Point"


class _FailingThenOkClient(_MockClient):
    calls: list[str] = []

    async def post(self, url, data=None, headers=None):
        _FailingThenOkClient.calls.append(url)
        if len(_FailingThenOkClient.calls) == 1:
            raise httpx.ConnectTimeout("timeout")
        return await super().post(url, data=data, headers=headers)


@pytest.mark.asyncio
async def test_overpass_falls_back_to_mirror(monkeypatch):
    _FailingThenOkClient.calls = []
    monkeypatch.setattr(overpass_svc.httpx, "AsyncClient", _FailingThenOkClient)
    result = await get_closures_along_route([(11.0, 48.0), (11.1, 48.1)])
    assert len(_FailingThenOkClient.calls) == 2
    assert _FailingThenOkClient.calls[0] != _FailingThenOkClient.calls[1]
    assert result["type"] == "FeatureCollection"


class _AlwaysFailingClient(_MockClient):
    async def post(self, url, data=None, headers=None):
        raise httpx.ConnectTimeout("timeout")


@pytest.mark.asyncio
async def test_overpass_raises_when_all_mirrors_fail(monkeypatch):
    monkeypatch.setattr(overpass_svc.httpx, "AsyncClient", _AlwaysFailingClient)
    with pytest.raises(httpx.ConnectTimeout):
        await get_closures_along_route([(11.0, 48.0), (11.1, 48.1)])
