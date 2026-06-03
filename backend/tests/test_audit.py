"""Tests for the security audit log: the record() helper and its wiring into
the login flow."""

import uuid

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock

from app.database import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.organization import Organization, UserOrganization
from app.models.user import User
from app.services import audit


# ── record() unit tests ────────────────────────────────────────────────────────

class _FakeSession:
    def __init__(self):
        self.added: list = []
        self.committed = False
        self.rolled_back = False

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


@pytest.mark.asyncio
async def test_record_persists_entry():
    db = _FakeSession()
    actor = uuid.uuid4()
    await audit.record(
        db, audit.LOGIN_SUCCESS, actor_id=actor, actor_email="u@example.com",
        detail={"scope": "org"},
    )
    assert db.committed is True
    assert len(db.added) == 1
    entry = db.added[0]
    assert isinstance(entry, AuditLog)
    assert entry.action == audit.LOGIN_SUCCESS
    assert entry.actor_id == actor
    assert entry.actor_email == "u@example.com"
    assert entry.detail == {"scope": "org"}


@pytest.mark.asyncio
async def test_record_never_raises_on_failure():
    class Boom(_FakeSession):
        def add(self, obj):
            raise RuntimeError("db down")

    db = Boom()
    # Must swallow the error and attempt a rollback — never propagate.
    await audit.record(db, audit.LOGIN_FAILURE, actor_email="x@example.com")
    assert db.rolled_back is True


# ── Login wiring ────────────────────────────────────────────────────────────────

def _user(email="t@example.com", pw="supersecret1", superadmin=False):
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.email = email
    u.is_active = True
    u.is_superadmin = superadmin
    u.mfa_enabled = False
    u.mfa_secret = None
    u.token_version = 0
    u.hashed_password = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    return u


def _org(slug="test-org"):
    o = MagicMock(spec=Organization)
    o.id = uuid.uuid4()
    o.slug = slug
    o.name = "Test Org"
    return o


def _mock_db(*values) -> AsyncMock:
    db = AsyncMock()
    results = []
    for v in values:
        r = MagicMock()
        r.scalar_one_or_none.return_value = v
        results.append(r)
    db.execute.side_effect = results
    return db


def _override(db):
    async def _gen():
        yield db
    return _gen


@pytest.mark.asyncio
async def test_login_success_records_audit(monkeypatch):
    calls = []

    async def _spy(db, action, **kwargs):
        calls.append((action, kwargs))

    monkeypatch.setattr("app.api.routes.auth.audit.record", _spy)

    user = _user()
    org = _org()
    mem = MagicMock(spec=UserOrganization)
    mem.role = "planer"
    db = _mock_db(user, org, mem)
    app.dependency_overrides[get_db] = _override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/auth/login",
                json={"email": user.email, "password": "supersecret1", "org_slug": org.slug},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert any(action == audit.LOGIN_SUCCESS for action, _ in calls)


@pytest.mark.asyncio
async def test_login_failure_records_audit(monkeypatch):
    calls = []

    async def _spy(db, action, **kwargs):
        calls.append((action, kwargs))

    monkeypatch.setattr("app.api.routes.auth.audit.record", _spy)

    user = _user()
    org = _org()
    db = _mock_db(user, org)  # password check fails before membership lookup
    app.dependency_overrides[get_db] = _override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/auth/login",
                json={"email": user.email, "password": "wrong-password", "org_slug": org.slug},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 401
    assert any(action == audit.LOGIN_FAILURE for action, _ in calls)
