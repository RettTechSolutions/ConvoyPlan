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


class _HereClient:
    """Mock-HTTP-Client für den HERE-Tile-Abruf (analog zu test_geocoding.py)."""

    payload: bytes = b"PNGDATA"
    raises: bool = False

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    async def get(self, url, params=None):
        if _HereClient.raises:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, content=_HereClient.payload, request=httpx.Request("GET", url))


@pytest.fixture(autouse=True)
def _setup_overrides():
    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db_override
    yield
    app.dependency_overrides.clear()


async def test_tile_without_here_key_falls_back_to_osm(monkeypatch):
    monkeypatch.setattr(tiles_route.geo_svc, "resolve_here_key", AsyncMock(return_value=""))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tiles/here/5/16/10", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "https://tile.openstreetmap.org/5/16/10.png"


async def test_tile_falls_back_to_osm_when_quota_exhausted(monkeypatch):
    monkeypatch.setattr(tiles_route.geo_svc, "resolve_here_key", AsyncMock(return_value="KEY"))
    monkeypatch.setattr(tiles_route.smartmaps_svc, "reserve_tile_quota", AsyncMock(return_value=False))
    monkeypatch.setattr(tiles_route.settings, "here_smartmaps_yearly_limit", 250000)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tiles/here/5/16/10", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "https://tile.openstreetmap.org/5/16/10.png"


async def test_tile_proxies_here_response(monkeypatch):
    monkeypatch.setattr(tiles_route.geo_svc, "resolve_here_key", AsyncMock(return_value="KEY"))
    monkeypatch.setattr(tiles_route.smartmaps_svc, "reserve_tile_quota", AsyncMock(return_value=True))
    monkeypatch.setattr(tiles_route.settings, "here_smartmaps_yearly_limit", 250000)
    _HereClient.raises = False
    _HereClient.payload = b"PNGDATA"
    monkeypatch.setattr(tiles_route.httpx, "AsyncClient", _HereClient)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tiles/here/5/16/10", follow_redirects=False)

    assert resp.status_code == 200
    assert resp.content == b"PNGDATA"
    assert resp.headers["content-type"] == "image/png"


async def test_tile_falls_back_to_osm_on_here_error(monkeypatch):
    monkeypatch.setattr(tiles_route.geo_svc, "resolve_here_key", AsyncMock(return_value="KEY"))
    monkeypatch.setattr(tiles_route.smartmaps_svc, "reserve_tile_quota", AsyncMock(return_value=True))
    monkeypatch.setattr(tiles_route.settings, "here_smartmaps_yearly_limit", 250000)
    _HereClient.raises = True
    monkeypatch.setattr(tiles_route.httpx, "AsyncClient", _HereClient)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tiles/here/5/16/10", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "https://tile.openstreetmap.org/5/16/10.png"
