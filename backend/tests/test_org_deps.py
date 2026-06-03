import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

from app.api.deps import get_token_data, get_org_context
from app.models.organization import Organization, UserOrganization
from app.models.user import User


def _make_token(user_id, org_id=None, org_slug=None, role=None, is_superadmin=False):
    from datetime import datetime, timedelta, timezone
    from jose import jwt
    from app.config import settings
    expire = datetime.now(timezone.utc) + timedelta(minutes=60)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "is_superadmin": is_superadmin,
        "org_id": str(org_id) if org_id else None,
        "org_slug": org_slug,
        "role": role,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def test_get_token_data_org_scoped():
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    token = _make_token(user_id, org_id=org_id, org_slug="test-org", role="planer")
    td = get_token_data(token)
    assert td.user_id == user_id
    assert td.org_id == org_id
    assert td.org_slug == "test-org"
    assert td.role == "planer"
    assert td.is_superadmin is False


def test_get_token_data_superadmin():
    user_id = uuid.uuid4()
    token = _make_token(user_id, is_superadmin=True)
    td = get_token_data(token)
    assert td.user_id == user_id
    assert td.org_id is None
    assert td.is_superadmin is True


def test_get_token_data_invalid_raises():
    with pytest.raises(HTTPException) as exc:
        get_token_data("not.a.token")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_org_context_success():
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    token = _make_token(user_id, org_id=org_id, org_slug="test", role="planer")

    user = MagicMock(spec=User)
    user.id = user_id
    user.is_active = True

    org = MagicMock(spec=Organization)
    org.id = org_id

    membership = MagicMock(spec=UserOrganization)
    membership.role = "planer"

    db = AsyncMock()
    db.get.side_effect = [user, org]
    mem_result = MagicMock()
    mem_result.scalar_one_or_none.return_value = membership
    db.execute.return_value = mem_result

    result_user, result_org, result_role = await get_org_context(token=token, raw_api_key=None, db=db)
    assert result_role == "planer"
    assert result_org is org


@pytest.mark.asyncio
async def test_get_org_context_no_credential_raises():
    with pytest.raises(HTTPException) as exc:
        await get_org_context(token=None, raw_api_key=None, db=AsyncMock())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_org_context_no_org_id_raises():
    token = _make_token(uuid.uuid4(), org_id=None)
    with pytest.raises(HTTPException) as exc:
        await get_org_context(token=token, raw_api_key=None, db=AsyncMock())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_org_context_not_member_raises():
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    token = _make_token(user_id, org_id=org_id, org_slug="test", role="planer")

    user = MagicMock(spec=User); user.id = user_id; user.is_active = True
    org = MagicMock(spec=Organization); org.id = org_id

    db = AsyncMock()
    db.get.side_effect = [user, org]
    mem_result = MagicMock()
    mem_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mem_result

    with pytest.raises(HTTPException) as exc:
        await get_org_context(token=token, raw_api_key=None, db=db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_org_context_api_key_success(monkeypatch):
    """An organization-scoped API key resolves to (owner, org, key.role)."""
    from app.api import deps as deps_mod

    org_id = uuid.uuid4()
    owner_id = uuid.uuid4()

    key = MagicMock()
    key.organization_id = org_id
    key.role = "fahrer"

    org = MagicMock(spec=Organization); org.id = org_id; org.owner_id = owner_id
    owner = MagicMock(spec=User); owner.id = owner_id; owner.is_active = True

    async def fake_resolve(db, raw):
        assert raw == "cvp_abcd_secret"
        return key

    monkeypatch.setattr(deps_mod.api_key_svc, "resolve_key", fake_resolve)

    db = AsyncMock()
    db.get.side_effect = [org, owner]

    result_user, result_org, result_role = await get_org_context(
        token=None, raw_api_key="cvp_abcd_secret", db=db
    )
    assert result_user is owner
    assert result_org is org
    assert result_role == "fahrer"


@pytest.mark.asyncio
async def test_get_org_context_api_key_invalid_raises(monkeypatch):
    from app.api import deps as deps_mod

    async def fake_resolve(db, raw):
        return None

    monkeypatch.setattr(deps_mod.api_key_svc, "resolve_key", fake_resolve)

    with pytest.raises(HTTPException) as exc:
        await get_org_context(token=None, raw_api_key="cvp_bad_key", db=AsyncMock())
    assert exc.value.status_code == 401
