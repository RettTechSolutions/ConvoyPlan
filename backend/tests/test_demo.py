"""Tests for the runtime demo-mode toggle (admin panel > env var fallback)
and the superadmin demo-session management endpoints."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock

from app.api.deps import get_db, require_superadmin
from app.main import app
from app.services import demo


def _db_returning(value: str | None) -> AsyncMock:
    """Mock db whose SystemSetting lookup returns a row with *value* (or no row)."""
    db = AsyncMock()
    result = MagicMock()
    if value is None:
        result.scalar_one_or_none.return_value = None
    else:
        setting = MagicMock()
        setting.value = value
        result.scalar_one_or_none.return_value = setting
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_db_setting_overrides_env(monkeypatch):
    monkeypatch.setattr("app.services.demo.settings.demo_enabled", False)
    assert await demo.is_demo_enabled(_db_returning("true")) is True

    monkeypatch.setattr("app.services.demo.settings.demo_enabled", True)
    assert await demo.is_demo_enabled(_db_returning("false")) is False


@pytest.mark.asyncio
async def test_env_is_fallback_when_db_unset(monkeypatch):
    monkeypatch.setattr("app.services.demo.settings.demo_enabled", True)
    assert await demo.is_demo_enabled(_db_returning(None)) is True

    monkeypatch.setattr("app.services.demo.settings.demo_enabled", False)
    assert await demo.is_demo_enabled(_db_returning(None)) is False


@pytest.mark.asyncio
async def test_garbage_db_value_falls_back_to_env(monkeypatch):
    monkeypatch.setattr("app.services.demo.settings.demo_enabled", False)
    assert await demo.is_demo_enabled(_db_returning("yes please")) is False


@pytest.mark.asyncio
async def test_set_demo_enabled_upserts():
    db = _db_returning(None)
    await demo.set_demo_enabled(db, True)
    db.add.assert_called_once()
    assert db.add.call_args[0][0].value == "true"
    db.commit.assert_awaited()

    db = _db_returning("true")
    await demo.set_demo_enabled(db, False)
    db.add.assert_not_called()
    db.commit.assert_awaited()


# ── Demo-session management (superadmin) ─────────────────────────────────────


def _superadmin():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.is_superadmin = True
    u.email = "admin@example.com"
    return u


@pytest.mark.asyncio
async def test_terminate_demo_session_404_when_missing():
    app.dependency_overrides[require_superadmin] = _superadmin

    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(f"/api/admin/demo-sessions/{uuid.uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_demo_sessions_empty():
    app.dependency_overrides[require_superadmin] = _superadmin

    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/admin/demo-sessions")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json() == []
