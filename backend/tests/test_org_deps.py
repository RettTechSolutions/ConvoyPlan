import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

from app.api.deps import get_token_data, get_org_context, TokenData
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
    token_data = TokenData(user_id=user_id, org_id=org_id, org_slug="test", role="planer")

    user = MagicMock(spec=User)
    user.id = user_id
    user.is_active = True
    user.token_version = 0

    org = MagicMock(spec=Organization)
    org.id = org_id

    membership = MagicMock(spec=UserOrganization)
    membership.role = "planer"

    db = AsyncMock()
    db.get.side_effect = [user, org]
    mem_result = MagicMock()
    mem_result.scalar_one_or_none.return_value = membership
    db.execute.return_value = mem_result

    result_user, result_org, result_role = await get_org_context(token_data, db)
    assert result_role == "planer"
    assert result_org is org


@pytest.mark.asyncio
async def test_get_org_context_no_org_id_raises():
    token_data = TokenData(user_id=uuid.uuid4(), org_id=None)
    with pytest.raises(HTTPException) as exc:
        await get_org_context(token_data, AsyncMock())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_org_context_not_member_raises():
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    token_data = TokenData(user_id=user_id, org_id=org_id, org_slug="test", role="planer")

    user = MagicMock(spec=User); user.id = user_id; user.is_active = True; user.token_version = 0
    org = MagicMock(spec=Organization); org.id = org_id

    db = AsyncMock()
    db.get.side_effect = [user, org]
    mem_result = MagicMock()
    mem_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mem_result

    with pytest.raises(HTTPException) as exc:
        await get_org_context(token_data, db)
    assert exc.value.status_code == 403
