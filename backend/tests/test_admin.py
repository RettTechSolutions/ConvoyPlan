import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.database import get_db


def _superadmin():
    user = MagicMock()
    user.is_superadmin = True
    return user


def _make_app_with_superadmin():
    from app.api.deps import require_superadmin
    app.dependency_overrides[require_superadmin] = lambda: _superadmin()
    return app


def _make_app_with_superadmin_and_db():
    from app.api.deps import require_superadmin
    app.dependency_overrides[require_superadmin] = lambda: _superadmin()
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    async def _db_override():
        yield db

    app.dependency_overrides[get_db] = _db_override
    return app


def _mock_github_client(*, latest_tag=None, latest_status=200, commit_sha=None, main_sha=None):
    """Mock httpx.AsyncClient for the update-status endpoint, dispatching by URL:
      - releases/latest  -> {"tag_name": latest_tag}  (status: latest_status)
      - commits/<tag>     -> {"sha": commit_sha}       (stable channel)
      - commits?sha=main  -> [{"sha": main_sha}]       (beta channel)
    """
    async def _get(url, **kwargs):
        resp = MagicMock()
        if "releases/latest" in url:
            resp.status_code = latest_status
            resp.is_success = 200 <= latest_status < 300
            resp.json.return_value = {"tag_name": latest_tag}
        elif "/commits/" in url:
            resp.status_code = 200
            resp.is_success = True
            resp.json.return_value = {"sha": commit_sha}
        else:  # commits?sha=main&per_page=1 (beta)
            resp.status_code = 200
            resp.is_success = True
            resp.json.return_value = [{"sha": main_sha}]
        return resp

    inner = MagicMock()
    inner.get = AsyncMock(side_effect=_get)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=inner)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.mark.asyncio
async def test_get_update_status_no_status_file():
    # Default channel is "stable": compares against the latest release commit.
    _make_app_with_superadmin_and_db()
    with patch("builtins.open", side_effect=FileNotFoundError), \
         patch("os.makedirs"), \
         patch("app.api.routes.admin.httpx.AsyncClient",
               return_value=_mock_github_client(latest_tag="v1.0.0", commit_sha="abc1234567890")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["deployed_sha"] is None
    assert data["remote_sha"] == "abc1234"
    assert data["update_available"] is False
    assert data["github_reachable"] is True
    assert data["channel"] == "stable"
    assert data["latest_release"] == "v1.0.0"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_status_update_available():
    _make_app_with_superadmin_and_db()
    status_content = json.dumps({"deployed_sha": "aaa1111", "deployed_at": "2026-05-18T10:00:00Z"})
    with patch("builtins.open", mock_open(read_data=status_content)), \
         patch("os.makedirs"), \
         patch("app.api.routes.admin.httpx.AsyncClient",
               return_value=_mock_github_client(latest_tag="v1.1.0", commit_sha="bbb2222abcdef")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["deployed_sha"] == "aaa1111"
    assert data["remote_sha"] == "bbb2222"
    assert data["update_available"] is True
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_status_stable_no_release():
    # Stable channel + repo without any release: not "out of date", just no release.
    _make_app_with_superadmin_and_db()
    with patch("builtins.open", side_effect=FileNotFoundError), \
         patch("os.makedirs"), \
         patch("app.api.routes.admin.httpx.AsyncClient",
               return_value=_mock_github_client(latest_status=404)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["github_reachable"] is True
    assert data["no_release"] is True
    assert data["remote_sha"] is None
    assert data["update_available"] is False
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_status_beta_channel_tracks_main():
    # Beta channel compares against the tip of main (every commit).
    _make_app_with_superadmin_and_db()
    status_content = json.dumps({"deployed_sha": "aaa1111", "deployed_at": "2026-05-18T10:00:00Z"})
    with patch("builtins.open", mock_open(read_data=status_content)), \
         patch("os.makedirs"), \
         patch("app.api.routes.admin.settings.update_channel", "beta"), \
         patch("app.api.routes.admin.httpx.AsyncClient",
               return_value=_mock_github_client(main_sha="ccc3333abcdef")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["channel"] == "beta"
    assert data["remote_sha"] == "ccc3333"
    assert data["update_available"] is True
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_status_github_unreachable():
    _make_app_with_superadmin_and_db()
    import httpx as _httpx
    inner = MagicMock()
    inner.get = AsyncMock(side_effect=_httpx.ConnectError("unreachable"))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=inner)
    ctx.__aexit__ = AsyncMock(return_value=False)
    with patch("builtins.open", side_effect=FileNotFoundError), \
         patch("os.makedirs"), \
         patch("app.api.routes.admin.httpx.AsyncClient", return_value=ctx):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["github_reachable"] is False
    assert data["remote_sha"] is None
    assert data["update_available"] is False
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_channel_default_env():
    _make_app_with_superadmin_and_db()
    with patch("os.makedirs"), patch("builtins.open", mock_open()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/settings/update-channel")
    assert r.status_code == 200
    data = r.json()
    assert data["channel"] in ("stable", "beta")
    assert data["source"] == "env"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_set_update_channel_persists_and_writes_file():
    _make_app_with_superadmin_and_db()
    m = mock_open()
    with patch("os.makedirs"), patch("builtins.open", m), \
         patch("app.api.routes.admin.audit.record", new=AsyncMock()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.put("/api/admin/settings/update-channel", json={"channel": "beta"})
    assert r.status_code == 204
    # The effective channel is mirrored to the shared volume for the updater.
    m().write.assert_any_call("beta")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_set_update_channel_rejects_invalid():
    _make_app_with_superadmin_and_db()
    with patch("os.makedirs"), patch("builtins.open", mock_open()), \
         patch("app.api.routes.admin.audit.record", new=AsyncMock()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.put("/api/admin/settings/update-channel", json={"channel": "nightly"})
    assert r.status_code == 422
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trigger_update_creates_file():
    _make_app_with_superadmin()
    m = mock_open()
    with patch("builtins.open", m), \
         patch("os.path.exists", return_value=False), \
         patch("os.makedirs"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/admin/trigger-update")
    assert r.status_code == 202
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trigger_update_409_when_already_triggered():
    _make_app_with_superadmin()
    with patch("os.path.exists", return_value=True):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/admin/trigger-update")
    assert r.status_code == 409
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trigger_update_503_when_volume_not_writable():
    # A non-writable /update_status volume (e.g. root-owned, predating the
    # non-root backend) must yield a clear 503 instead of a bare 500.
    _make_app_with_superadmin()
    with patch("os.path.exists", return_value=False), \
         patch("os.makedirs"), \
         patch("builtins.open", side_effect=PermissionError("read-only")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/admin/trigger-update")
    assert r.status_code == 503
    app.dependency_overrides.clear()
