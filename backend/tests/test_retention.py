"""Tests for data retention (T5) and subject-rights endpoints (T5b)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock

from app.api.deps import get_db, require_superadmin
from app.main import app
from app.services import retention


# ── Retention purge ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_all_returns_counts_and_audits(monkeypatch):
    db = AsyncMock()
    r_pos = MagicMock(); r_pos.rowcount = 3
    r_audit = MagicMock(); r_audit.rowcount = 0
    r_links = MagicMock(); r_links.rowcount = 2
    r_demo = MagicMock(); r_demo.all.return_value = []  # no expired demo orgs
    db.execute.side_effect = [r_pos, r_audit, r_links, r_demo]

    recorded = []

    async def _spy(_db, action, **kwargs):
        recorded.append((action, kwargs.get("detail")))

    monkeypatch.setattr("app.services.retention.audit.record", _spy)

    counts = await retention.run_all(db)

    assert counts == {"positions": 3, "audit_logs": 0, "share_links": 2, "demo_sessions": 0}
    db.commit.assert_awaited()
    # an audit entry is written because something was deleted
    assert recorded and recorded[0][0] == "retention.purge"
    assert recorded[0][1] == counts


@pytest.mark.asyncio
async def test_run_all_skips_audit_when_nothing_deleted(monkeypatch):
    db = AsyncMock()
    results = [MagicMock(rowcount=0) for _ in range(3)]
    r_demo = MagicMock(); r_demo.all.return_value = []
    db.execute.side_effect = results + [r_demo]

    recorded = []

    async def _spy(_db, action, **kwargs):
        recorded.append(action)

    monkeypatch.setattr("app.services.retention.audit.record", _spy)

    counts = await retention.run_all(db)
    assert counts == {"positions": 0, "audit_logs": 0, "share_links": 0, "demo_sessions": 0}
    assert recorded == []  # nothing deleted → no audit entry


# ── Subject rights ───────────────────────────────────────────────────────────────

def _superadmin():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.is_superadmin = True
    u.email = "admin@example.com"
    return u


@pytest.mark.asyncio
async def test_erase_user_data_rejects_self():
    sa = _superadmin()
    app.dependency_overrides[require_superadmin] = lambda: sa

    db = AsyncMock()
    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.request("DELETE", f"/api/admin/users/{sa.id}/data")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_erase_user_data_404_when_missing():
    sa = _superadmin()
    app.dependency_overrides[require_superadmin] = lambda: sa

    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.request("DELETE", f"/api/admin/users/{uuid.uuid4()}/data")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404
