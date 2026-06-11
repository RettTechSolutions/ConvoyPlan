"""Tests for the runtime demo-mode toggle (admin panel > env var fallback)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

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
