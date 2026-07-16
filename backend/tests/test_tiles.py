import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user
from app.api.routes import tiles as tiles_route
from app.database import get_db
from app.main import app


def _user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.is_active = True
    u.is_superadmin = False
    return u


async def _db_override():
    yield MagicMock()


class _SmartMapsClient:
    """Mock-HTTP-Client für SmartMaps- und OSM-Tile-Abrufe (analog zu test_geocoding.py)."""

    payload: bytes = b"WEBPDATA"        # SmartMaps-Antwort (WebP)
    osm_payload: bytes = b"OSMPNGDATA"  # OSM-Fallback-Antwort (PNG)
    raises: bool = False                # SmartMaps-Abruf schlägt fehl
    osm_raises: bool = False            # OSM-Fallback schlägt ebenfalls fehl

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    async def get(self, url, params=None):
        # SmartMaps wird mit apiKey-Query aufgerufen, der OSM-Fallback ohne
        # Params — daran (statt an einem URL-Substring) unterscheiden wir die
        # beiden Upstreams.
        if params is None:
            if _SmartMapsClient.osm_raises:
                raise httpx.ConnectError("osm boom")
            return httpx.Response(
                200,
                content=_SmartMapsClient.osm_payload,
                headers={"content-type": "image/png"},
                request=httpx.Request("GET", url),
            )
        if _SmartMapsClient.raises:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, content=_SmartMapsClient.payload, request=httpx.Request("GET", url))


@pytest.fixture(autouse=True)
def _setup_overrides():
    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db_override
    _SmartMapsClient.raises = False
    _SmartMapsClient.osm_raises = False
    _SmartMapsClient.payload = b"WEBPDATA"
    _SmartMapsClient.osm_payload = b"OSMPNGDATA"
    yield
    app.dependency_overrides.clear()


async def test_tile_without_key_falls_back_to_osm(monkeypatch):
    monkeypatch.setattr(tiles_route.settings, "smartmaps_api_key", "")
    monkeypatch.setattr(tiles_route.httpx, "AsyncClient", _SmartMapsClient)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tiles/smartmaps/5/16/10", follow_redirects=False)

    # Same-origin-Proxy statt 302-Redirect: OSM-Kachel wird serverseitig durchgereicht.
    assert resp.status_code == 200
    assert resp.content == b"OSMPNGDATA"
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["cache-control"] == "public, max-age=86400"


async def test_tile_falls_back_to_osm_when_quota_exhausted(monkeypatch):
    monkeypatch.setattr(tiles_route.settings, "smartmaps_api_key", "KEY")
    monkeypatch.setattr(tiles_route.smartmaps_svc, "reserve_tile_quota", AsyncMock(return_value=False))
    monkeypatch.setattr(tiles_route.settings, "smartmaps_yearly_limit", 250000)
    monkeypatch.setattr(tiles_route.httpx, "AsyncClient", _SmartMapsClient)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tiles/smartmaps/5/16/10", follow_redirects=False)

    assert resp.status_code == 200
    assert resp.content == b"OSMPNGDATA"
    assert resp.headers["content-type"] == "image/png"


async def test_tile_cap_disabled_skips_reservation(monkeypatch):
    monkeypatch.setattr(tiles_route.settings, "smartmaps_api_key", "KEY")
    reserve = AsyncMock(return_value=False)
    monkeypatch.setattr(tiles_route.smartmaps_svc, "reserve_tile_quota", reserve)
    monkeypatch.setattr(tiles_route.settings, "smartmaps_yearly_limit", 0)
    _SmartMapsClient.raises = False
    _SmartMapsClient.payload = b"WEBPDATA"
    monkeypatch.setattr(tiles_route.httpx, "AsyncClient", _SmartMapsClient)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tiles/smartmaps/5/16/10", follow_redirects=False)

    assert resp.status_code == 200
    assert resp.content == b"WEBPDATA"
    # Deckel deaktiviert (limit=0) -> keine Reservierung
    reserve.assert_not_awaited()


async def test_tile_proxies_smartmaps_response(monkeypatch):
    monkeypatch.setattr(tiles_route.settings, "smartmaps_api_key", "KEY")
    reserve = AsyncMock(return_value=True)
    monkeypatch.setattr(tiles_route.smartmaps_svc, "reserve_tile_quota", reserve)
    monkeypatch.setattr(tiles_route.settings, "smartmaps_yearly_limit", 250000)
    _SmartMapsClient.raises = False
    _SmartMapsClient.payload = b"WEBPDATA"
    monkeypatch.setattr(tiles_route.httpx, "AsyncClient", _SmartMapsClient)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tiles/smartmaps/5/16/10", follow_redirects=False)

    assert resp.status_code == 200
    assert resp.content == b"WEBPDATA"
    assert resp.headers["content-type"] == "image/webp"
    assert resp.headers["cache-control"] == "public, max-age=86400"
    # Happy-Path muss tatsächlich ein Kontingent reservieren
    reserve.assert_awaited_once()


async def test_tile_falls_back_to_osm_on_smartmaps_error(monkeypatch):
    monkeypatch.setattr(tiles_route.settings, "smartmaps_api_key", "KEY")
    monkeypatch.setattr(tiles_route.smartmaps_svc, "reserve_tile_quota", AsyncMock(return_value=True))
    monkeypatch.setattr(tiles_route.settings, "smartmaps_yearly_limit", 250000)
    _SmartMapsClient.raises = True
    monkeypatch.setattr(tiles_route.httpx, "AsyncClient", _SmartMapsClient)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tiles/smartmaps/5/16/10", follow_redirects=False)

    # SmartMaps-Fehler -> serverseitiger OSM-Proxy (kein Redirect).
    assert resp.status_code == 200
    assert resp.content == b"OSMPNGDATA"


async def test_tile_returns_502_when_smartmaps_and_osm_both_fail(monkeypatch):
    monkeypatch.setattr(tiles_route.settings, "smartmaps_api_key", "KEY")
    monkeypatch.setattr(tiles_route.smartmaps_svc, "reserve_tile_quota", AsyncMock(return_value=True))
    monkeypatch.setattr(tiles_route.settings, "smartmaps_yearly_limit", 250000)
    _SmartMapsClient.raises = True
    _SmartMapsClient.osm_raises = True
    monkeypatch.setattr(tiles_route.httpx, "AsyncClient", _SmartMapsClient)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tiles/smartmaps/5/16/10", follow_redirects=False)

    # Auch OSM nicht erreichbar -> still auf 502 degradieren, nicht mit 500 crashen.
    assert resp.status_code == 502
