import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

from app.models.convoy import Convoy
from app.models.organization import UserOrganization
from app.models.user import User
from app.models.vehicle import Vehicle


# --- helpers ---

def _user(uid=None):
    u = MagicMock(spec=User)
    u.id = uid or uuid.uuid4()
    return u


def _convoy(owner_id=None, org_id=None):
    c = MagicMock(spec=Convoy)
    c.id = uuid.uuid4()
    c.owner_id = owner_id or uuid.uuid4()
    c.organization_id = org_id
    return c


def _vehicle(owner_id=None):
    v = MagicMock(spec=Vehicle)
    v.id = uuid.uuid4()
    v.owner_id = owner_id or uuid.uuid4()
    return v


def _membership(user_id, org_id, role):
    m = MagicMock(spec=UserOrganization)
    m.user_id = user_id
    m.organization_id = org_id
    m.role = role
    return m


def _db(*results):
    """Mock db.execute() with one MagicMock result per call in sequence.
    Pass a list for results that use .scalars().all(); a single object for scalar_one_or_none()."""
    db = AsyncMock()
    mock_results = []
    for r in results:
        mr = MagicMock()
        if isinstance(r, list):
            mr.scalars.return_value.all.return_value = r
            mr.scalar_one_or_none.return_value = r[0] if r else None
        else:
            mr.scalar_one_or_none.return_value = r
            mr.scalars.return_value.all.return_value = [r] if r is not None else []
        mock_results.append(mr)
    db.execute.side_effect = mock_results
    return db


# --- convoy access tests ---

@pytest.mark.asyncio
async def test_convoy_owner_has_delete_access():
    from app.api.guards import get_convoy_access
    user = _user()
    convoy = _convoy(owner_id=user.id)
    db = _db(convoy)
    result = await get_convoy_access(convoy.id, user, db, require="delete")
    assert result is convoy


@pytest.mark.asyncio
async def test_convoy_not_found_raises_404():
    from app.api.guards import get_convoy_access
    user = _user()
    db = _db(None)
    with pytest.raises(HTTPException) as exc:
        await get_convoy_access(uuid.uuid4(), user, db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_non_member_raises_403():
    from app.api.guards import get_convoy_access
    user = _user()
    org_id = uuid.uuid4()
    convoy = _convoy(org_id=org_id)
    db = _db(convoy, None)  # convoy found, no membership
    with pytest.raises(HTTPException) as exc:
        await get_convoy_access(convoy.id, user, db, require="read")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_convoy_no_org_raises_403_for_non_owner():
    from app.api.guards import get_convoy_access
    user = _user()
    convoy = _convoy(org_id=None)  # no org linked
    db = _db(convoy)
    with pytest.raises(HTTPException) as exc:
        await get_convoy_access(convoy.id, user, db, require="read")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_beobachter_can_read():
    from app.api.guards import get_convoy_access
    user = _user()
    org_id = uuid.uuid4()
    convoy = _convoy(org_id=org_id)
    mem = _membership(user.id, org_id, "beobachter")
    db = _db(convoy, mem)
    result = await get_convoy_access(convoy.id, user, db, require="read")
    assert result is convoy


@pytest.mark.asyncio
async def test_beobachter_cannot_write():
    from app.api.guards import get_convoy_access
    user = _user()
    org_id = uuid.uuid4()
    convoy = _convoy(org_id=org_id)
    mem = _membership(user.id, org_id, "beobachter")
    db = _db(convoy, mem)
    with pytest.raises(HTTPException) as exc:
        await get_convoy_access(convoy.id, user, db, require="write")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_beobachter_cannot_update_status():
    from app.api.guards import get_convoy_access
    user = _user()
    org_id = uuid.uuid4()
    convoy = _convoy(org_id=org_id)
    mem = _membership(user.id, org_id, "beobachter")
    db = _db(convoy, mem)
    with pytest.raises(HTTPException) as exc:
        await get_convoy_access(convoy.id, user, db, require="fahrer")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_fahrer_can_update_status():
    from app.api.guards import get_convoy_access
    user = _user()
    org_id = uuid.uuid4()
    convoy = _convoy(org_id=org_id)
    mem = _membership(user.id, org_id, "fahrer")
    db = _db(convoy, mem)
    result = await get_convoy_access(convoy.id, user, db, require="fahrer")
    assert result is convoy


@pytest.mark.asyncio
async def test_fahrer_cannot_write():
    from app.api.guards import get_convoy_access
    user = _user()
    org_id = uuid.uuid4()
    convoy = _convoy(org_id=org_id)
    mem = _membership(user.id, org_id, "fahrer")
    db = _db(convoy, mem)
    with pytest.raises(HTTPException) as exc:
        await get_convoy_access(convoy.id, user, db, require="write")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_planer_can_write():
    from app.api.guards import get_convoy_access
    user = _user()
    org_id = uuid.uuid4()
    convoy = _convoy(org_id=org_id)
    mem = _membership(user.id, org_id, "planer")
    db = _db(convoy, mem)
    result = await get_convoy_access(convoy.id, user, db, require="write")
    assert result is convoy


@pytest.mark.asyncio
async def test_planer_cannot_delete():
    from app.api.guards import get_convoy_access
    user = _user()
    org_id = uuid.uuid4()
    convoy = _convoy(org_id=org_id)
    mem = _membership(user.id, org_id, "planer")
    db = _db(convoy, mem)
    with pytest.raises(HTTPException) as exc:
        await get_convoy_access(convoy.id, user, db, require="delete")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_delete():
    from app.api.guards import get_convoy_access
    user = _user()
    org_id = uuid.uuid4()
    convoy = _convoy(org_id=org_id)
    mem = _membership(user.id, org_id, "admin")
    db = _db(convoy, mem)
    result = await get_convoy_access(convoy.id, user, db, require="delete")
    assert result is convoy


# --- explicit-role enforcement (H1: API-key role must apply on owner fast-path) ---

@pytest.mark.asyncio
async def test_supplied_role_enforced_on_owned_convoy():
    """When an effective role is supplied (org context / API key), it must be
    enforced even when the acting user OWNS the convoy. Otherwise a beobachter
    API key (which acts as the org owner) escalates to write/delete."""
    from app.api.guards import get_convoy_access
    user = _user()
    convoy = _convoy(owner_id=user.id)  # user owns it → would hit the fast-path
    db = _db(convoy)
    with pytest.raises(HTTPException) as exc:
        await get_convoy_access(convoy.id, user, db, require="write", role="beobachter")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_supplied_role_allows_when_sufficient_on_owned_convoy():
    from app.api.guards import get_convoy_access
    user = _user()
    convoy = _convoy(owner_id=user.id)
    db = _db(convoy)
    result = await get_convoy_access(convoy.id, user, db, require="write", role="planer")
    assert result is convoy


@pytest.mark.asyncio
async def test_supplied_role_blocks_delete_for_planer_owner():
    from app.api.guards import get_convoy_access
    user = _user()
    convoy = _convoy(owner_id=user.id)
    db = _db(convoy)
    with pytest.raises(HTTPException) as exc:
        await get_convoy_access(convoy.id, user, db, require="delete", role="planer")
    assert exc.value.status_code == 403


# --- vehicle access tests ---

@pytest.mark.asyncio
async def test_vehicle_owner_has_delete_access():
    from app.api.guards import get_vehicle_access
    user = _user()
    vehicle = _vehicle(owner_id=user.id)
    db = _db(vehicle)
    result = await get_vehicle_access(vehicle.id, user, db, require="delete")
    assert result is vehicle


@pytest.mark.asyncio
async def test_vehicle_not_found_raises_404():
    from app.api.guards import get_vehicle_access
    user = _user()
    db = _db(None)
    with pytest.raises(HTTPException) as exc:
        await get_vehicle_access(uuid.uuid4(), user, db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_vehicle_non_member_raises_403():
    from app.api.guards import get_vehicle_access
    user = _user()
    vehicle = _vehicle()
    db = _db(vehicle, [])  # no shared memberships
    with pytest.raises(HTTPException) as exc:
        await get_vehicle_access(vehicle.id, user, db, require="read")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_vehicle_beobachter_can_read():
    from app.api.guards import get_vehicle_access
    user = _user()
    org_id = uuid.uuid4()
    vehicle = _vehicle()
    mem = _membership(user.id, org_id, "beobachter")
    db = _db(vehicle, [mem])
    result = await get_vehicle_access(vehicle.id, user, db, require="read")
    assert result is vehicle


@pytest.mark.asyncio
async def test_vehicle_beobachter_cannot_write():
    from app.api.guards import get_vehicle_access
    user = _user()
    org_id = uuid.uuid4()
    vehicle = _vehicle()
    mem = _membership(user.id, org_id, "beobachter")
    db = _db(vehicle, [mem])
    with pytest.raises(HTTPException) as exc:
        await get_vehicle_access(vehicle.id, user, db, require="write")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_vehicle_planer_can_write():
    from app.api.guards import get_vehicle_access
    user = _user()
    org_id = uuid.uuid4()
    vehicle = _vehicle()
    mem = _membership(user.id, org_id, "planer")
    db = _db(vehicle, [mem])
    result = await get_vehicle_access(vehicle.id, user, db, require="write")
    assert result is vehicle


@pytest.mark.asyncio
async def test_vehicle_planer_cannot_delete():
    from app.api.guards import get_vehicle_access
    user = _user()
    org_id = uuid.uuid4()
    vehicle = _vehicle()
    mem = _membership(user.id, org_id, "planer")
    db = _db(vehicle, [mem])
    with pytest.raises(HTTPException) as exc:
        await get_vehicle_access(vehicle.id, user, db, require="delete")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_vehicle_admin_can_delete():
    from app.api.guards import get_vehicle_access
    user = _user()
    org_id = uuid.uuid4()
    vehicle = _vehicle()
    mem = _membership(user.id, org_id, "admin")
    db = _db(vehicle, [mem])
    result = await get_vehicle_access(vehicle.id, user, db, require="delete")
    assert result is vehicle


# ── Org-Context Guard ────────────────────────────────────────────────────────

from app.api.deps import get_org_context, OrgCtx
from app.models.organization import Organization

def _org(org_id=None):
    o = MagicMock(spec=Organization)
    o.id = org_id or uuid.uuid4()
    return o


@pytest.mark.asyncio
async def test_list_convoys_returns_only_org_convoys(monkeypatch):
    """get_org_context muss als Dependency genutzt werden — nicht owner_id allein."""
    from app.api.routes.convoys import router
    # Prüfe dass get_org_context in den Dependencies der list-Route vorkommt
    list_route = next(r for r in router.routes if getattr(r, "path", "").rstrip("/").endswith("/convoys") and "GET" in getattr(r, "methods", []))
    dep_callables = [d.dependency for d in list_route.dependencies]
    assert get_org_context in dep_callables, "list_convoys muss get_org_context nutzen"
