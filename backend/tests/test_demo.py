"""Tests for the runtime demo-mode toggle (admin panel > env var fallback)
and the superadmin demo-session management endpoints."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from unittest.mock import AsyncMock, MagicMock

from app.api.deps import get_db, require_superadmin
from app.main import app
from app.models.demo_origin import DemoOrigin
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
async def test_session_hours_db_overrides_env(monkeypatch):
    monkeypatch.setattr("app.services.demo.settings.demo_session_hours", 24)
    assert await demo.get_demo_session_hours(_db_returning("72")) == 72
    assert await demo.get_demo_session_hours(_db_returning(None)) == 24
    # invalid or out-of-bounds values fall back to env
    assert await demo.get_demo_session_hours(_db_returning("banana")) == 24
    assert await demo.get_demo_session_hours(_db_returning("0")) == 24
    assert await demo.get_demo_session_hours(_db_returning("99999")) == 24


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


# ── IP-Karenzzeit ─────────────────────────────────────────────────────────────

def _db_with_origin(origin: DemoOrigin | None) -> AsyncMock:
    """Mock-DB, deren DemoOrigin-Abfrage *origin* (oder nichts) liefert."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = origin
    db.execute.return_value = result
    return db


def _origin(*, hours_ago: float, sessions: int = 1) -> DemoOrigin:
    stamp = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return DemoOrigin(ip="203.0.113.7", first_created_at=stamp, last_created_at=stamp,
                      sessions=sessions)


@pytest.mark.asyncio
async def test_first_demo_from_ip_is_allowed_and_recorded():
    db = _db_with_origin(None)
    assert await demo.claim_ip(db, "203.0.113.7", 24) is None
    db.add.assert_called_once()
    assert db.add.call_args.args[0].ip == "203.0.113.7"


@pytest.mark.asyncio
async def test_second_demo_within_cooldown_is_blocked():
    db = _db_with_origin(_origin(hours_ago=1))
    retry_after = await demo.claim_ip(db, "203.0.113.7", 24)
    # 23 Stunden Restzeit (auf die Sekunde genau, deshalb ein Toleranzfenster).
    assert retry_after is not None
    assert 23 * 3600 - 5 <= retry_after <= 23 * 3600 + 5
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_demo_allowed_again_after_cooldown_expired():
    origin = _origin(hours_ago=25, sessions=1)
    db = _db_with_origin(origin)
    assert await demo.claim_ip(db, "203.0.113.7", 24) is None
    # Kein neuer Datensatz, aber ein aktualisierter Zeitstempel und Zähler.
    db.add.assert_not_called()
    assert origin.sessions == 2
    assert (datetime.now(timezone.utc) - origin.last_created_at).total_seconds() < 5


@pytest.mark.asyncio
async def test_cooldown_zero_disables_the_lock():
    db = _db_with_origin(_origin(hours_ago=0))
    assert await demo.claim_ip(db, "203.0.113.7", 0) is None
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_without_client_ip_there_is_nothing_to_lock():
    db = _db_with_origin(None)
    assert await demo.claim_ip(db, None, 24) is None
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_concurrent_claims_lose_the_race_instead_of_slipping_through():
    db = _db_with_origin(None)
    db.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate key"))
    retry_after = await demo.claim_ip(db, "203.0.113.7", 24)
    assert retry_after == 24 * 3600
    db.rollback.assert_awaited()


@pytest.mark.asyncio
async def test_demo_session_endpoint_answers_429_during_cooldown(monkeypatch):
    """Der Endpunkt lehnt die zweite Demo derselben IP mit Retry-After ab."""
    monkeypatch.setattr("app.services.demo.settings.demo_enabled", True)
    monkeypatch.setattr("app.services.demo.settings.demo_ip_cooldown_hours", 24)

    unset = MagicMock(); unset.scalar_one_or_none.return_value = None
    origin_row = MagicMock(); origin_row.scalar_one_or_none.return_value = _origin(hours_ago=2)
    db = AsyncMock()
    # 1) demo.enabled  2) demo.ip_cooldown_hours  3) demo_origins-Abfrage
    db.execute.side_effect = [unset, unset, origin_row]

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/auth/demo-session")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0
    assert "24 Stunden" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_demo_session_endpoint_names_the_reason_when_switched_off(monkeypatch):
    """Bei abgeschalteter Demo nennt die Absage den Grund — die Startseite zeigt
    diesen Text unverändert an, „später nochmal versuchen" wäre dort falsch."""
    monkeypatch.setattr("app.services.demo.settings.demo_enabled", False)

    unset = MagicMock(); unset.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.return_value = unset

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/auth/demo-session")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 503
    assert "abgeschaltet" in resp.json()["detail"]
