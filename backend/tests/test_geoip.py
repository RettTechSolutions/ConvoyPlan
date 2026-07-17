"""Tests for the best-effort demo GeoIP lookup (app.services.geoip)."""

import uuid

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services import geoip


class _Client:
    """Stub for httpx.AsyncClient returning a canned ipapi.co payload."""

    payload: dict = {}
    raises: bool = False
    calls: list[str] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        _Client.calls.append(url)
        if _Client.raises:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json=_Client.payload, request=httpx.Request("GET", url))


@pytest.fixture(autouse=True)
def _reset_client(monkeypatch):
    _Client.payload = {"city": "München", "region": "Bayern", "country_name": "Germany"}
    _Client.raises = False
    _Client.calls = []
    monkeypatch.setattr(geoip.httpx, "AsyncClient", _Client)


# ── lookup_location ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("ip", [None, "", "not-an-ip", "testclient", "127.0.0.1", "10.0.0.5", "192.168.1.20", "::1"])
async def test_private_or_invalid_ips_are_not_looked_up(ip):
    assert await geoip.lookup_location(ip) is None
    assert _Client.calls == []


@pytest.mark.asyncio
async def test_public_ip_resolves_to_location():
    assert await geoip.lookup_location("93.184.216.34") == "München, Bayern, Germany"
    assert len(_Client.calls) == 1


@pytest.mark.asyncio
async def test_partial_payload_skips_missing_fields():
    _Client.payload = {"city": None, "region": "", "country_name": "Germany"}
    assert await geoip.lookup_location("93.184.216.34") == "Germany"


@pytest.mark.asyncio
async def test_error_payload_returns_none():
    _Client.payload = {"error": True, "reason": "RateLimited"}
    assert await geoip.lookup_location("93.184.216.34") is None


@pytest.mark.asyncio
async def test_network_failure_returns_none():
    _Client.raises = True
    assert await geoip.lookup_location("93.184.216.34") is None


# ── resolve_demo_origin ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_skips_db_when_lookup_empty(monkeypatch):
    """No location → the background task must not open a DB session."""
    session_factory = MagicMock(side_effect=AssertionError("DB must not be touched"))
    monkeypatch.setattr(geoip, "get_db_session", session_factory)
    await geoip.resolve_demo_origin(uuid.uuid4(), "127.0.0.1")
    session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_stores_location_on_demo_org(monkeypatch):
    org = MagicMock()
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = org
    db.execute.return_value = result

    class _Ctx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(geoip, "get_db_session", lambda: _Ctx())
    await geoip.resolve_demo_origin(uuid.uuid4(), "93.184.216.34")
    assert org.demo_created_location == "München, Bayern, Germany"
    db.commit.assert_awaited()
