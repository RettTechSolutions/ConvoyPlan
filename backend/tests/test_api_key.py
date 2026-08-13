import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.deps import get_org_context, require_system_read
from app.models.api_key import SCOPE_ORGANIZATION, SCOPE_SYSTEM
from app.models.user import User
from app.services import api_key as svc


def test_generate_key_roundtrip():
    gen = svc.generate_key()
    assert gen.full_key == f"cvp_{gen.prefix}_{gen.secret}"
    assert len(gen.prefix) == 8
    # The stored hash must verify the secret but never equal it.
    assert gen.key_hash != gen.secret
    import bcrypt
    assert bcrypt.checkpw(gen.secret.encode(), gen.key_hash.encode())


def test_parse_valid_and_invalid():
    gen = svc.generate_key()
    assert svc._parse(gen.full_key) == (gen.prefix, gen.secret)
    # secrets with underscores survive (partition on first "_" only)
    assert svc._parse("cvp_pre_a_b") == ("pre", "a_b")
    assert svc._parse("") is None
    assert svc._parse("noprefix_x") is None
    assert svc._parse("cvp_onlyprefix") is None


def test_is_expired():
    key = MagicMock()
    key.expires_at = None
    assert svc.is_expired(key) is False
    key.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    assert svc.is_expired(key) is True
    key.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    assert svc.is_expired(key) is False


@pytest.mark.asyncio
async def test_resolve_key_rejects_revoked():
    gen = svc.generate_key()
    key = MagicMock()
    key.prefix = gen.prefix
    key.key_hash = gen.key_hash
    key.revoked = True

    result = MagicMock()
    result.scalar_one_or_none.return_value = key
    db = AsyncMock()
    db.execute.return_value = result

    assert await svc.resolve_key(db, gen.full_key) is None


@pytest.mark.asyncio
async def test_resolve_key_rejects_wrong_secret():
    gen = svc.generate_key()
    key = MagicMock()
    key.prefix = gen.prefix
    key.key_hash = gen.key_hash
    key.revoked = False

    result = MagicMock()
    result.scalar_one_or_none.return_value = key
    db = AsyncMock()
    db.execute.return_value = result

    # Same prefix but a different secret must not validate.
    assert await svc.resolve_key(db, f"cvp_{gen.prefix}_wrongsecret") is None


@pytest.mark.asyncio
async def test_resolve_key_accepts_valid():
    gen = svc.generate_key()
    key = MagicMock()
    key.prefix = gen.prefix
    key.key_hash = gen.key_hash
    key.revoked = False
    key.expires_at = None
    key.last_used_at = None

    result = MagicMock()
    result.scalar_one_or_none.return_value = key
    db = AsyncMock()
    db.execute.return_value = result

    resolved = await svc.resolve_key(db, gen.full_key)
    assert resolved is key
    # last_used_at refreshed and committed
    assert key.last_used_at is not None
    db.commit.assert_awaited()


# ── Scope separation ──────────────────────────────────────────────────────────
#
# System keys read instance-wide figures that span every tenant; organization
# keys act inside one tenant. Neither may cross into the other's territory.

def _superadmin_token(user_id, is_superadmin=True):
    import jwt as _jwt
    from app.config import settings
    expire = datetime.now(timezone.utc) + timedelta(minutes=60)
    return _jwt.encode(
        {"sub": str(user_id), "exp": expire, "is_superadmin": is_superadmin, "tv": 0},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _fake_key(scope):
    key = MagicMock()
    key.scope = scope
    key.organization_id = None if scope == SCOPE_SYSTEM else uuid.uuid4()
    key.role = "beobachter"
    return key


@pytest.fixture
def resolves_to(monkeypatch):
    """Make deps.api_key_svc.resolve_key return a prepared key (or None)."""
    def _install(key):
        monkeypatch.setattr(deps.api_key_svc, "resolve_key", AsyncMock(return_value=key))
    return _install


@pytest.mark.asyncio
async def test_system_read_accepts_system_key(resolves_to):
    resolves_to(_fake_key(SCOPE_SYSTEM))
    # No acting user: the metrics endpoints only read.
    assert await require_system_read(token=None, raw_api_key="cvp_x_y", db=AsyncMock()) is None


@pytest.mark.asyncio
async def test_system_read_rejects_org_key(resolves_to):
    """The regression this guards: an org key must not see instance-wide data."""
    resolves_to(_fake_key(SCOPE_ORGANIZATION))
    with pytest.raises(HTTPException) as exc:
        await require_system_read(token=None, raw_api_key="cvp_x_y", db=AsyncMock())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_system_read_rejects_unknown_key(resolves_to):
    resolves_to(None)
    with pytest.raises(HTTPException) as exc:
        await require_system_read(token=None, raw_api_key="cvp_x_y", db=AsyncMock())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_system_read_rejects_anonymous():
    with pytest.raises(HTTPException) as exc:
        await require_system_read(token=None, raw_api_key=None, db=AsyncMock())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_system_read_accepts_superadmin_token():
    user_id = uuid.uuid4()
    user = MagicMock(spec=User)
    user.id = user_id
    user.is_active = True
    user.is_superadmin = True
    user.token_version = 0

    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db = AsyncMock()
    db.execute.return_value = result

    resolved = await require_system_read(
        token=_superadmin_token(user_id), raw_api_key=None, db=db
    )
    assert resolved is user


@pytest.mark.asyncio
async def test_system_read_rejects_ordinary_token():
    token = _superadmin_token(uuid.uuid4(), is_superadmin=False)
    with pytest.raises(HTTPException) as exc:
        await require_system_read(token=token, raw_api_key=None, db=AsyncMock())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_org_context_rejects_system_key(resolves_to):
    """Mirror image: a system key carries no org and must not act on tenant data."""
    resolves_to(_fake_key(SCOPE_SYSTEM))
    with pytest.raises(HTTPException) as exc:
        await get_org_context(token=None, raw_api_key="cvp_x_y", db=AsyncMock())
    assert exc.value.status_code == 403
