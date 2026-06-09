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


# ── Convoy (Marschbefehl) wiring ─────────────────────────────────────────────

def _request():
    req = MagicMock()
    req.headers = {"user-agent": "pytest", "x-forwarded-for": "203.0.113.7"}
    req.client = MagicMock()
    req.client.host = "203.0.113.7"
    return req


def _audit_spy(monkeypatch, module):
    calls = []

    async def _spy(db, action, **kwargs):
        calls.append((action, kwargs))

    monkeypatch.setattr(f"{module}.audit.record", _spy)
    return calls


@pytest.mark.asyncio
async def test_create_convoy_records_audit(monkeypatch):
    from app.api.routes import convoys
    from app.schemas.convoy import ConvoyCreate

    calls = _audit_spy(monkeypatch, "app.api.routes.convoys")
    monkeypatch.setattr(convoys, "_serialize_convoy", lambda c: {"ok": True})

    user = MagicMock(spec=User); user.id = uuid.uuid4(); user.email = "p@example.com"
    org = MagicMock(spec=Organization); org.id = uuid.uuid4()

    db = AsyncMock()
    db.execute.return_value = MagicMock()  # scalar_one() -> MagicMock, ignored by stub

    await convoys.create_convoy(
        data=ConvoyCreate(name="Marsch A"),
        request=_request(),
        ctx=(user, org, "planer"),
        db=db,
    )

    actions = [a for a, _ in calls]
    assert audit.CONVOY_CREATED in actions
    _, kwargs = next(c for c in calls if c[0] == audit.CONVOY_CREATED)
    assert kwargs["org_id"] == org.id
    assert kwargs["actor_id"] == user.id
    assert kwargs["detail"]["name"] == "Marsch A"


@pytest.mark.asyncio
async def test_update_convoy_records_changed_fields(monkeypatch):
    from app.api.routes import convoys
    from app.schemas.convoy import ConvoyUpdate

    calls = _audit_spy(monkeypatch, "app.api.routes.convoys")
    monkeypatch.setattr(convoys, "_serialize_convoy", lambda c: {"ok": True})

    user = MagicMock(spec=User); user.id = uuid.uuid4(); user.email = "p@example.com"
    org = MagicMock(spec=Organization); org.id = uuid.uuid4()
    convoy = MagicMock(); convoy.organization_id = org.id; convoy.name = "Marsch A"

    async def _access(*a, **k):
        return convoy

    monkeypatch.setattr(convoys, "get_convoy_access", _access)

    db = AsyncMock()
    db.execute.return_value = MagicMock()

    await convoys.update_convoy(
        convoy_id=uuid.uuid4(),
        data=ConvoyUpdate(auftrag="neuer Auftrag"),
        request=_request(),
        ctx=(user, org, "planer"),
        db=db,
    )

    _, kwargs = next(c for c in calls if c[0] == audit.CONVOY_UPDATED)
    assert "auftrag" in kwargs["detail"]["changed"]


@pytest.mark.asyncio
async def test_delete_convoy_records_audit(monkeypatch):
    from app.api.routes import convoys

    calls = _audit_spy(monkeypatch, "app.api.routes.convoys")

    user = MagicMock(spec=User); user.id = uuid.uuid4(); user.email = "p@example.com"
    org = MagicMock(spec=Organization); org.id = uuid.uuid4()
    convoy = MagicMock(); convoy.organization_id = org.id; convoy.name = "Marsch A"

    async def _access(*a, **k):
        return convoy

    monkeypatch.setattr(convoys, "get_convoy_access", _access)

    await convoys.delete_convoy(
        convoy_id=uuid.uuid4(),
        request=_request(),
        ctx=(user, org, "delete"),
        db=AsyncMock(),
    )

    _, kwargs = next(c for c in calls if c[0] == audit.CONVOY_DELETED)
    assert kwargs["detail"]["name"] == "Marsch A"


# ── Share-Link wiring ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_share_link_records_audit(monkeypatch):
    from app.api.routes import share_links
    from app.schemas.share_link import ShareLinkCreate

    calls = _audit_spy(monkeypatch, "app.api.routes.share_links")

    user = MagicMock(spec=User); user.id = uuid.uuid4(); user.email = "p@example.com"
    org_id = uuid.uuid4()
    convoy = MagicMock(); convoy.organization_id = org_id

    async def _access(*a, **k):
        return convoy

    monkeypatch.setattr(share_links, "get_convoy_access", _access)

    async def _slug(db):
        return "abc123"

    monkeypatch.setattr(share_links.share_links_svc, "generate_unique_slug", _slug)

    from datetime import datetime, timezone
    monkeypatch.setattr(
        share_links, "_to_response",
        lambda link, request: share_links.ShareLinkResponse(
            id=uuid.uuid4(), slug=link.slug, scope=link.scope, requires_password=False,
            created_at=datetime.now(timezone.utc), last_accessed_at=None,
            access_count=0, revoked=False, url="http://test/track/abc123",
        ),
    )

    db = AsyncMock()

    await share_links.create_share_link(
        convoy_id=uuid.uuid4(),
        data=ShareLinkCreate(password_mode="none"),
        request=_request(),
        db=db,
        current_user=user,
    )

    _, kwargs = next(c for c in calls if c[0] == audit.SHARE_LINK_CREATED)
    assert kwargs["org_id"] == org_id
    assert kwargs["detail"]["slug"] == "abc123"
    assert kwargs["detail"]["requires_password"] is False


@pytest.mark.asyncio
async def test_revoke_share_link_records_audit(monkeypatch):
    from app.api.routes import share_links

    calls = _audit_spy(monkeypatch, "app.api.routes.share_links")

    user = MagicMock(spec=User); user.id = uuid.uuid4(); user.email = "p@example.com"
    org_id = uuid.uuid4()
    convoy = MagicMock(); convoy.organization_id = org_id

    async def _access(*a, **k):
        return convoy

    monkeypatch.setattr(share_links, "get_convoy_access", _access)

    link = MagicMock(); link.slug = "abc123"; link.convoy_id = uuid.uuid4(); link.revoked = False
    db = AsyncMock()
    result = MagicMock(); result.scalar_one_or_none.return_value = link
    db.execute.return_value = result

    async def _revoke(cid):
        return None

    monkeypatch.setattr(share_links.tracking_manager, "revoke_connections", _revoke)

    await share_links.revoke_share_link(
        convoy_id=uuid.uuid4(),
        link_id=uuid.uuid4(),
        request=_request(),
        db=db,
        current_user=user,
    )

    _, kwargs = next(c for c in calls if c[0] == audit.SHARE_LINK_REVOKED)
    assert kwargs["detail"]["slug"] == "abc123"
