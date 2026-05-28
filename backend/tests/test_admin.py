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


def _mock_github_client(sha: str):
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = [{"sha": sha}]
    inner = MagicMock()
    inner.get = AsyncMock(return_value=mock_resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=inner)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.mark.asyncio
async def test_get_update_status_no_status_file():
    _make_app_with_superadmin_and_db()
    with patch("builtins.open", side_effect=FileNotFoundError), \
         patch("app.api.routes.admin.httpx.AsyncClient", return_value=_mock_github_client("abc1234567890")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["deployed_sha"] is None
    assert data["remote_sha"] == "abc1234"
    assert data["update_available"] is False
    assert data["github_reachable"] is True
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_status_update_available():
    _make_app_with_superadmin_and_db()
    status_content = json.dumps({"deployed_sha": "aaa1111", "deployed_at": "2026-05-18T10:00:00Z"})
    with patch("builtins.open", mock_open(read_data=status_content)), \
         patch("app.api.routes.admin.httpx.AsyncClient", return_value=_mock_github_client("bbb2222abcdef")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["deployed_sha"] == "aaa1111"
    assert data["remote_sha"] == "bbb2222"
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
