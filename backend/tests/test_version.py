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


@pytest.mark.asyncio
async def test_version_endpoint_hint_is_channel_aware(monkeypatch):
    """The public footer hint must honour the active release channel. On a
    nightly instance the target is the last nightly build (a commit SHA, no
    release tag), so `latest` reports that SHA and `update_available` mirrors
    the channel-aware update-state — never a comparison against a stable
    release."""
    version_module._state_cache.clear()
    monkeypatch.setattr(settings, "update_check_enabled", True)
    monkeypatch.setattr(settings, "app_version", "1.0.2-6-g258ce81")

    async def fake_resolve_channel(db):
        return "nightly", "db"

    async def fake_fetch_update_state(db):
        return {
            "deployed_sha": "258ce81",
            "remote_sha": "8e421a8",
            "update_available": True,
            "channel": "nightly",
            "latest_release": None,      # nightly has no release tag
            "ahead_of_release": False,
        }

    monkeypatch.setattr(version_module, "resolve_channel", fake_resolve_channel)
    monkeypatch.setattr(version_module, "fetch_update_state", fake_fetch_update_state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/version")

    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "1.0.2-6-g258ce81"
    assert body["latest"] == "8e421a8"        # nightly target SHA, not a stable tag
    assert body["update_available"] is True


@pytest.mark.asyncio
async def test_version_endpoint_suppresses_hint_when_ahead(monkeypatch):
    """When the running build is newer than the channel target (e.g. a former
    nightly now on stable), the update-state reports update_available False and
    the footer must not show a spurious 'update available' hint."""
    version_module._state_cache.clear()
    monkeypatch.setattr(settings, "update_check_enabled", True)

    async def fake_resolve_channel(db):
        return "stable", "env"

    async def fake_fetch_update_state(db):
        return {
            "deployed_sha": "258ce81",
            "remote_sha": "8afe9bd",
            "update_available": False,   # deployed build is ahead of the release
            "channel": "stable",
            "latest_release": "v1.0.2",
            "ahead_of_release": True,
        }

    monkeypatch.setattr(version_module, "resolve_channel", fake_resolve_channel)
    monkeypatch.setattr(version_module, "fetch_update_state", fake_fetch_update_state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/version")

    assert resp.status_code == 200
    body = resp.json()
    assert body["update_available"] is False
    assert body["latest"] == "v1.0.2"         # release tag still surfaced


def test_core_str_strips_metadata():
    core = version_module._core_str
    assert core("1.0.0") == "1.0.0"
    assert core("v1.0.0") == "1.0.0"
    assert core("1.0.0+abc1234") == "1.0.0"
    assert core("1.0.0-3-gabc1234") == "1.0.0"
    assert core("0.0.0-dev") == "0.0.0"
    assert core("2026.1.1") == "2026.1.1"
    assert core("v2026.1.1+abc1234") == "2026.1.1"
    assert core("unknown") is None
    assert core(None) is None


@pytest.mark.asyncio
async def test_changelog_endpoint_returns_version_core(monkeypatch):
    """With the update check disabled (autouse fixture) the changelog endpoint
    reports the running version core and no notes, instead of hitting GitHub."""
    # Clear the per-version cache so this test isn't served a stale entry.
    version_module._changelog_cache.clear()
    monkeypatch.setattr(settings, "app_version", "1.2.3-5-gdeadbee")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/version/changelog")

    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "1.2.3"        # core only, no commit suffix
    assert body["body"] is None              # network disabled in tests
