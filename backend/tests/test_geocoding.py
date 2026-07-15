"""Tests für die Adresssuche (HERE Geocoding & Search mit Photon-Fallback)."""
import httpx
import pytest

from app.services import geocoding as geo


# ── HERE-Parsing ─────────────────────────────────────────────────────


def test_here_results_house_number():
    data = {"items": [{
        "title": "Invalidenstraße 117, 10115 Berlin, Deutschland",
        "resultType": "houseNumber",
        "position": {"lat": 52.53041, "lng": 13.38527},
        "address": {
            "street": "Invalidenstraße", "houseNumber": "117",
            "postalCode": "10115", "city": "Berlin", "state": "Berlin",
            "countryName": "Deutschland",
        },
    }]}
    res = geo._here_results(data)
    assert len(res) == 1
    assert res[0]["lat"] == 52.53041 and res[0]["lon"] == 13.38527
    assert res[0]["primary"] == "Invalidenstraße 117"
    assert res[0]["secondary"] == "10115 Berlin, Deutschland"


def test_here_results_skips_items_without_position():
    # Kategorie-/Ketten-Vorschläge (z. B. "Restaurants") haben keine Position.
    data = {"items": [
        {"title": "Restaurants", "resultType": "categoryQuery"},
        {"title": "Berlin", "resultType": "locality",
         "position": {"lat": 52.52, "lng": 13.40},
         "address": {"city": "Berlin", "state": "Berlin", "countryName": "Deutschland"}},
    ]}
    res = geo._here_results(data)
    assert len(res) == 1
    assert res[0]["primary"] == "Berlin"


def test_here_results_poi_uses_title():
    data = {"items": [{
        "title": "Brandenburger Tor, Pariser Platz, 10117 Berlin",
        "resultType": "place",
        "position": {"lat": 52.5163, "lng": 13.3777},
        "address": {"city": "Berlin", "postalCode": "10117",
                    "state": "Berlin", "countryName": "Deutschland"},
    }]}
    res = geo._here_results(data)
    assert res[0]["primary"] == "Brandenburger Tor"


# ── Photon-Parsing ───────────────────────────────────────────────────


def test_photon_results_parsing():
    data = {"features": [{
        "geometry": {"coordinates": [13.38527, 52.53041]},
        "properties": {
            "street": "Invalidenstraße", "housenumber": "117",
            "postcode": "10115", "city": "Berlin", "state": "Berlin",
            "country": "Deutschland",
        },
    }]}
    res = geo._photon_results(data)
    assert res[0]["lat"] == 52.53041 and res[0]["lon"] == 13.38527
    assert res[0]["primary"] == "Invalidenstraße 117"
    assert res[0]["secondary"] == "10115 Berlin, Deutschland"


def test_photon_results_skips_incomplete_geometry():
    data = {"features": [{"geometry": {"coordinates": [13.0]}, "properties": {}}]}
    assert geo._photon_results(data) == []


# ── search(): Anbieterwahl & Fallback ────────────────────────────────


class _Client:
    """Mock-HTTP-Client, der je nach URL HERE- oder Photon-JSON liefert."""
    here_payload: dict = {}
    photon_payload: dict = {}
    here_raises: bool = False

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    async def get(self, url, params=None):
        if url == geo.HERE_AUTOSUGGEST_URL:
            if _Client.here_raises:
                raise httpx.ConnectError("boom")
            return httpx.Response(200, json=_Client.here_payload,
                                  request=httpx.Request("GET", url))
        return httpx.Response(200, json=_Client.photon_payload,
                              request=httpx.Request("GET", url))


@pytest.fixture(autouse=True)
def _reset_client():
    _Client.here_raises = False
    _Client.here_payload = {"items": [{
        "title": "Teststraße 1, 10000 Teststadt",
        "position": {"lat": 50.0, "lng": 10.0},
        "address": {"street": "Teststraße", "houseNumber": "1",
                    "postalCode": "10000", "city": "Teststadt"},
    }]}
    _Client.photon_payload = {"features": [{
        "geometry": {"coordinates": [10.0, 50.0]},
        "properties": {"street": "Photonweg", "housenumber": "2", "city": "Photonstadt"},
    }]}


async def test_search_too_short_returns_empty():
    out = await geo.search("a", here_key="H")
    assert out == {"provider": None, "results": []}


async def test_search_uses_here_when_key_set(monkeypatch):
    monkeypatch.setattr(geo.httpx, "AsyncClient", _Client)
    out = await geo.search("Teststraße", here_key="H")
    assert out["provider"] == "here"
    assert out["results"][0]["primary"] == "Teststraße 1"


async def test_search_falls_back_to_photon_without_key(monkeypatch):
    monkeypatch.setattr(geo.httpx, "AsyncClient", _Client)
    out = await geo.search("Photonweg", here_key="")
    assert out["provider"] == "photon"
    assert out["results"][0]["primary"] == "Photonweg 2"


async def test_search_falls_back_to_photon_when_here_fails(monkeypatch):
    _Client.here_raises = True
    monkeypatch.setattr(geo.httpx, "AsyncClient", _Client)
    out = await geo.search("egal", here_key="H")
    assert out["provider"] == "photon"
    assert out["results"][0]["primary"] == "Photonweg 2"


# ── Key-Auflösung ────────────────────────────────────────────────────


async def test_resolve_key_prefers_explicit_here_api_key(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "here_api_key", "GEOCODE_KEY")
    # DB wird bei gesetztem here_api_key gar nicht abgefragt.
    assert await geo.resolve_here_key(db=None) == "GEOCODE_KEY"


async def test_resolve_key_falls_back_to_traffic_key(monkeypatch):
    from app.config import settings
    from app.services import traffic_flow
    monkeypatch.setattr(settings, "here_api_key", "")

    async def _fake_resolve(db):
        return traffic_flow.FlowConfig(here_key="TRAFFIC_KEY")

    monkeypatch.setattr(traffic_flow, "resolve_config", _fake_resolve)
    assert await geo.resolve_here_key(db=object()) == "TRAFFIC_KEY"
