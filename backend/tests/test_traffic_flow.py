"""Tests für die Live-Verkehrslage (HERE/TomTom) – gemockte Anbieter-Antworten."""
import httpx
import pytest

from app.config import settings
from app.services import traffic_flow as tf


@pytest.fixture(autouse=True)
def _reset_keys(monkeypatch):
    monkeypatch.setattr(settings, "here_traffic_api_key", "")
    monkeypatch.setattr(settings, "tomtom_traffic_api_key", "")
    monkeypatch.setattr(settings, "traffic_flow_provider", "")
    yield


# ── Anbieterauswahl / Gating ─────────────────────────────────────────


def test_no_provider_when_no_key():
    assert tf.configured_provider() is None


def test_here_preferred_when_both_set(monkeypatch):
    monkeypatch.setattr(settings, "here_traffic_api_key", "H")
    monkeypatch.setattr(settings, "tomtom_traffic_api_key", "T")
    assert tf.configured_provider() == "here"


def test_forced_provider(monkeypatch):
    monkeypatch.setattr(settings, "here_traffic_api_key", "H")
    monkeypatch.setattr(settings, "tomtom_traffic_api_key", "T")
    monkeypatch.setattr(settings, "traffic_flow_provider", "tomtom")
    assert tf.configured_provider() == "tomtom"


async def test_flow_empty_without_key():
    result = await tf.flow_along_route([(11.0, 48.0), (11.1, 48.1)])
    assert result == {"type": "FeatureCollection", "features": []}


# ── jamFactor-Ableitung ──────────────────────────────────────────────


def test_jam_from_speeds():
    assert tf._jam_from_speeds(0, 100, False) == 10.0     # steht → 10
    assert tf._jam_from_speeds(100, 100, False) == 0.0    # frei → 0
    assert tf._jam_from_speeds(50, 100, False) == 5.0
    assert tf._jam_from_speeds(80, 100, True) == 10.0     # Sperrung → 10
    assert tf._jam_from_speeds(None, 100, False) is None


# ── HERE ─────────────────────────────────────────────────────────────


def test_here_features_parsing():
    data = {"results": [{
        "location": {"shape": {"links": [
            {"points": [{"lat": 48.00, "lng": 11.00}, {"lat": 48.01, "lng": 11.01}]}
        ]}},
        "currentFlow": {"speed": 5.0, "freeFlow": 20.0, "jamFactor": 7.3, "traversability": "open"},
    }]}
    feats = tf._here_features(data)
    assert len(feats) == 1
    assert feats[0]["geometry"]["coordinates"] == [[11.00, 48.00], [11.01, 48.01]]
    assert feats[0]["properties"]["jamFactor"] == 7.3
    assert feats[0]["properties"]["source"] == "here"


class _Client:
    payload: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    async def get(self, url, params=None):
        return httpx.Response(200, json=_Client.payload, request=httpx.Request("GET", url))


async def test_here_flow_along_route(monkeypatch):
    monkeypatch.setattr(settings, "here_traffic_api_key", "H")
    _Client.payload = {"results": [{
        "location": {"shape": {"links": [
            {"points": [{"lat": 48.05, "lng": 11.05}, {"lat": 48.06, "lng": 11.06}]}
        ]}},
        "currentFlow": {"speed": 3.0, "freeFlow": 15.0, "jamFactor": 8.0},
    }]}
    monkeypatch.setattr(tf.httpx, "AsyncClient", _Client)
    # Route führt durch (11.05, 48.05) → Feature liegt im Korridor
    route = [(11.0, 48.0), (11.05, 48.05), (11.1, 48.1)]
    result = await tf.flow_along_route(route, corridor_m=3000)
    assert result["features"], "erwartet Verkehrslage-Features im Korridor"
    assert result["features"][0]["properties"]["source"] == "here"
    assert result["features"][0]["properties"]["jamFactor"] == 8.0


# ── TomTom ───────────────────────────────────────────────────────────


def test_tomtom_feature_parsing():
    data = {"flowSegmentData": {
        "frc": "FRC3", "currentSpeed": 20, "freeFlowSpeed": 50, "roadClosure": False,
        "coordinates": {"coordinate": [
            {"latitude": 48.0, "longitude": 11.0}, {"latitude": 48.01, "longitude": 11.01}]},
    }}
    f = tf._tomtom_feature(data)
    assert f["geometry"]["coordinates"] == [[11.0, 48.0], [11.01, 48.01]]
    assert f["properties"]["source"] == "tomtom"
    assert f["properties"]["jamFactor"] == 6.0  # (1 - 20/50)*10


def test_tomtom_road_closure_max_jam():
    data = {"flowSegmentData": {"currentSpeed": 0, "freeFlowSpeed": 50, "roadClosure": True,
            "coordinates": {"coordinate": [
                {"latitude": 48.0, "longitude": 11.0}, {"latitude": 48.01, "longitude": 11.01}]}}}
    assert tf._tomtom_feature(data)["properties"]["jamFactor"] == 10.0


async def test_tomtom_flow_along_route(monkeypatch):
    monkeypatch.setattr(settings, "tomtom_traffic_api_key", "T")
    _Client.payload = {"flowSegmentData": {
        "frc": "FRC2", "currentSpeed": 10, "freeFlowSpeed": 50, "roadClosure": False,
        "coordinates": {"coordinate": [
            {"latitude": 48.05, "longitude": 11.05}, {"latitude": 48.055, "longitude": 11.055}]},
    }}
    monkeypatch.setattr(tf.httpx, "AsyncClient", _Client)
    route = [(11.0, 48.0), (11.05, 48.05), (11.1, 48.1)]
    result = await tf.flow_along_route(route, corridor_m=3000)
    assert result["features"]
    assert result["features"][0]["properties"]["source"] == "tomtom"
    assert result["features"][0]["properties"]["jamFactor"] == 8.0  # (1-10/50)*10
