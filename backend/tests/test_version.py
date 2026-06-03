import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.api.routes import version as version_module
from app.config import settings


@pytest.mark.asyncio
async def test_version_endpoint_returns_build_info(monkeypatch):
    """The public /api/version endpoint reports the build version and SHA and,
    with the update check disabled (autouse fixture), reports no update."""
    monkeypatch.setattr(settings, "app_version", "0.9.0")
    monkeypatch.setenv("GIT_SHA", "abcdef1234567")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/version")

    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "0.9.0"
    assert body["sha"] == "abcdef1"          # truncated to 7 chars
    assert body["latest"] is None            # update check disabled in tests
    assert body["update_available"] is False


def test_normalize_parses_versions():
    norm = version_module._normalize
    assert norm("0.9.0") == (0, 9, 0)
    assert norm("v0.9.0") == (0, 9, 0)
    assert norm("0.9.0+abc1234") == (0, 9, 0)
    assert norm("0.9.0-3-gabc1234") == (0, 9, 0)
    assert norm("unknown") is None
    assert norm(None) is None


def test_update_available_comparison():
    norm = version_module._normalize
    assert norm("0.9.1") > norm("0.9.0")
    assert norm("0.10.0") > norm("0.9.9")
    assert not norm("0.9.0") > norm("0.9.0")
