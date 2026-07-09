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


def test_normalize_parses_calver_scheme():
    """The YYYY.MASTER.FIX scheme (e.g. 2026.1.1) parses like any dotted
    version, including the 'v' prefix and build/describe suffixes."""
    norm = version_module._normalize
    assert norm("2026.1.1") == (2026, 1, 1)
    assert norm("v2026.1.1") == (2026, 1, 1)
    assert norm("2026.1.1+abc1234") == (2026, 1, 1)
    assert norm("2026.1.1-3-gabc1234") == (2026, 1, 1)


def test_update_available_comparison():
    norm = version_module._normalize
    assert norm("0.9.1") > norm("0.9.0")
    assert norm("0.10.0") > norm("0.9.9")
    assert not norm("0.9.0") > norm("0.9.0")


def test_update_available_comparison_across_scheme_switch():
    """Ordering must hold both within the CalVer scheme and across the switch
    from the old SemVer numbers, so the 'update available' hint stays correct."""
    norm = version_module._normalize
    # Within the new scheme: fix, master and year each bump correctly.
    assert norm("2026.1.2") > norm("2026.1.1")   # fix bump
    assert norm("2026.2.1") > norm("2026.1.9")   # master bump
    assert norm("2027.1.1") > norm("2026.9.9")   # year rollover
    # Across the switch: the first CalVer release sorts above the last SemVer.
    assert norm("2026.1.1") > norm("1.0.2")


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
