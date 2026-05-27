# Org-Rechte Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the four-tier org role model (`admin | planer | fahrer | beobachter`) so org membership controls who can read, write, and delete convoys and vehicles.

**Architecture:** New `guards.py` module with two guard functions. `_convoy_query` and `list_vehicles` expanded to include org-accessible objects. All write/delete endpoints replace the old `_get_owned_convoy` / `owner_id`-only check with guard calls. `ConvoyCreate` gains `organization_id` so convoys can be linked to an org at creation.

**Tech Stack:** FastAPI, SQLAlchemy async, pytest with AsyncMock for unit tests.

---

## File Map

| File | Change |
|---|---|
| `backend/app/api/guards.py` | **Create** — `get_convoy_access`, `get_vehicle_access` |
| `backend/tests/test_guards.py` | **Create** — unit tests for all role combinations |
| `backend/app/schemas/convoy.py` | **Modify** — add `organization_id` to `ConvoyCreate` and `ConvoyResponse` |
| `backend/app/api/routes/convoys.py` | **Modify** — expand list query, replace all `_get_owned_convoy` calls |
| `backend/app/api/routes/vehicles.py` | **Modify** — expand list query, add guards to read/write/delete |
| `backend/app/api/routes/tracking.py` | **Modify** — replace `_assert_convoy_access`, add `fahrer` check |

---

## Task 1: `guards.py` and unit tests (TDD)

**Files:**
- Create: `backend/app/api/guards.py`
- Create: `backend/tests/test_guards.py`

### Step 1: Write the failing tests

Create `backend/tests/test_guards.py`:

```python
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
```

### Step 2: Run tests — expect ImportError (guards.py doesn't exist yet)

```bash
cd backend && pytest tests/test_guards.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'app.api.guards'`

### Step 3: Create `backend/app/api/guards.py`

```python
import uuid
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.convoy import Convoy
from app.models.organization import UserOrganization
from app.models.user import User
from app.models.vehicle import Vehicle

ROLE_ORDER: dict[str, int] = {
    "beobachter": 0,
    "fahrer": 1,
    "planer": 2,
    "admin": 3,
}

_REQUIRED_ROLE: dict[str, str] = {
    "read": "beobachter",
    "fahrer": "fahrer",
    "write": "planer",
    "delete": "admin",
}


async def get_convoy_access(
    convoy_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    require: Literal["read", "fahrer", "write", "delete"] = "read",
) -> Convoy:
    result = await db.execute(select(Convoy).where(Convoy.id == convoy_id))
    convoy = result.scalar_one_or_none()
    if not convoy:
        raise HTTPException(404, "Convoy not found")

    if convoy.owner_id == user.id:
        return convoy

    if not convoy.organization_id:
        raise HTTPException(403, "Not a member of this organisation")

    mem = await db.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == user.id,
            UserOrganization.organization_id == convoy.organization_id,
        )
    )
    membership = mem.scalar_one_or_none()
    if not membership:
        raise HTTPException(403, "Not a member of this organisation")

    required_role = _REQUIRED_ROLE[require]
    if ROLE_ORDER.get(membership.role, -1) < ROLE_ORDER[required_role]:
        raise HTTPException(403, f"Insufficient role: requires {required_role}")

    return convoy


async def get_vehicle_access(
    vehicle_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    require: Literal["read", "write", "delete"] = "read",
) -> Vehicle:
    result = await db.execute(select(Vehicle).where(Vehicle.id == vehicle_id))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(404, "Vehicle not found")

    if vehicle.owner_id == user.id:
        return vehicle

    # Find user's memberships in orgs shared with the vehicle owner
    owner_org_ids = (
        select(UserOrganization.organization_id)
        .where(UserOrganization.user_id == vehicle.owner_id)
        .scalar_subquery()
    )
    mem_result = await db.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == user.id,
            UserOrganization.organization_id.in_(owner_org_ids),
        )
    )
    memberships = mem_result.scalars().all()

    if not memberships:
        raise HTTPException(403, "Not a member of this organisation")

    best_level = max(ROLE_ORDER.get(m.role, -1) for m in memberships)
    required_role = _REQUIRED_ROLE[require]
    if best_level < ROLE_ORDER[required_role]:
        raise HTTPException(403, f"Insufficient role: requires {required_role}")

    return vehicle
```

### Step 4: Run tests — expect all pass

```bash
cd backend && pytest tests/test_guards.py -v
```

Expected: 22 tests PASS

### Step 5: Commit

```bash
git add backend/app/api/guards.py backend/tests/test_guards.py
git commit -m "feat: add org-role guards (get_convoy_access, get_vehicle_access)"
```

---

## Task 2: Schema update + `convoys.py`

**Files:**
- Modify: `backend/app/schemas/convoy.py`
- Modify: `backend/app/api/routes/convoys.py`

### Step 1: Add `organization_id` to convoy schemas

In `backend/app/schemas/convoy.py`, add `organization_id: uuid.UUID | None = None` to `ConvoyCreate` (after `organization: str | None = None`) and to `ConvoyResponse` (after `organization: str | None`):

```python
class ConvoyCreate(BaseModel):
    name: str
    organization: str | None = None
    organization_id: uuid.UUID | None = None   # ← add this line
    start_time: datetime | None = None
    # ... rest unchanged
```

```python
class ConvoyResponse(BaseModel):
    id: uuid.UUID
    name: str
    organization: str | None
    organization_id: uuid.UUID | None = None   # ← add this line
    start_time: datetime | None
    # ... rest unchanged
```

### Step 2: Update imports in `convoys.py`

Replace the existing `from sqlalchemy import select, delete` with:

```python
from sqlalchemy import select, delete, or_
```

Add to the existing imports block:

```python
from app.api.guards import get_convoy_access, get_vehicle_access, ROLE_ORDER
from app.models.organization import UserOrganization
```

### Step 3: Replace `_convoy_query`

The current `_convoy_query` filters only by `owner_id`. Replace the entire function:

```python
def _convoy_query(user_id: uuid.UUID):
    org_ids_subq = (
        select(UserOrganization.organization_id)
        .where(UserOrganization.user_id == user_id)
        .scalar_subquery()
    )
    return (
        select(Convoy)
        .where(
            or_(
                Convoy.owner_id == user_id,
                Convoy.organization_id.in_(org_ids_subq),
            )
        )
        .options(
            selectinload(Convoy.convoy_vehicles).selectinload(ConvoyVehicle.vehicle),
            selectinload(Convoy.waypoints),
        )
    )
```

### Step 4: Add `organization_id` to `_serialize_convoy`

In `_serialize_convoy`, add one line after `"organization": convoy.organization,`:

```python
"organization_id": convoy.organization_id,
```

### Step 5: Update `create_convoy` — add org role check

In `create_convoy`, after `convoy_data = data.model_dump(...)`, add a check before creating the convoy:

```python
if data.organization_id:
    mem = await db.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == current_user.id,
            UserOrganization.organization_id == data.organization_id,
        )
    )
    membership = mem.scalar_one_or_none()
    if not membership or ROLE_ORDER.get(membership.role, -1) < ROLE_ORDER["planer"]:
        raise HTTPException(403, "Insufficient role: requires planer")
```

### Step 6: Update `update_convoy` — use write guard

Replace the current body of `update_convoy` (from the first `result = await db.execute(...)` through the `if not convoy` check) with:

```python
async def update_convoy(
    convoy_id: uuid.UUID,
    data: ConvoyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convoy = await get_convoy_access(convoy_id, current_user, db, require="write")
    update_data = data.model_dump(exclude_none=True, exclude={"start_point", "end_point"})
    for key, value in update_data.items():
        setattr(convoy, key, value)
    if data.start_point:
        convoy.start_point = geo_svc.point_to_wkt(data.start_point.lat, data.start_point.lon)
    if data.end_point:
        convoy.end_point = geo_svc.point_to_wkt(data.end_point.lat, data.end_point.lon)
    await db.commit()

    result = await db.execute(_convoy_query(current_user.id).where(Convoy.id == convoy_id))
    return _serialize_convoy(result.scalar_one())
```

### Step 7: Update `delete_convoy` — use delete guard

Replace the body of `delete_convoy`:

```python
async def delete_convoy(
    convoy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convoy = await get_convoy_access(convoy_id, current_user, db, require="delete")
    await db.delete(convoy)
    await db.commit()
```

### Step 8: Replace all `_get_owned_convoy` calls

Replace every call to `_get_owned_convoy(convoy_id, current_user.id, db)` in the endpoints listed below. Use the require level shown.

| Endpoint | Old call | New call |
|---|---|---|
| `add_vehicle_to_convoy` | `_get_owned_convoy(...)` | `await get_convoy_access(convoy_id, current_user, db, require="write")` |
| `remove_vehicle_from_convoy` | `_get_owned_convoy(...)` | `await get_convoy_access(convoy_id, current_user, db, require="write")` |
| `list_waypoints` | `_get_owned_convoy(...)` | `await get_convoy_access(convoy_id, current_user, db, require="read")` |
| `create_waypoint` | `_get_owned_convoy(...)` | `await get_convoy_access(convoy_id, current_user, db, require="write")` |
| `update_waypoint` | `_get_owned_convoy(...)` | `await get_convoy_access(convoy_id, current_user, db, require="write")` |
| `delete_waypoint` | `_get_owned_convoy(...)` | `await get_convoy_access(convoy_id, current_user, db, require="write")` |
| `reorder_waypoints` | `_get_owned_convoy(...)` | `convoy = await get_convoy_access(convoy_id, current_user, db, require="write")` |
| `list_sub_convoys` | `_get_owned_convoy(...)` | `await get_convoy_access(convoy_id, current_user, db, require="read")` |
| `create_sub_convoy` | `_get_owned_convoy(...)` | `await get_convoy_access(convoy_id, current_user, db, require="write")` |

Note: `reorder_waypoints` uses the returned convoy object (`convoy.id`), so keep the assignment.

### Step 9: Fix vehicle check in `add_vehicle_to_convoy`

Replace:
```python
vehicle_result = await db.execute(
    select(Vehicle).where(Vehicle.id == data.vehicle_id, Vehicle.owner_id == current_user.id)
)
if not vehicle_result.scalar_one_or_none():
    raise HTTPException(status_code=404, detail="Vehicle not found")
```

With:
```python
await get_vehicle_access(data.vehicle_id, current_user, db, require="read")
```

### Step 10: Remove `_get_owned_convoy`

Delete the entire `_get_owned_convoy` function (lines 320–327 in the original file). It is no longer used.

### Step 11: Run smoke test

```bash
cd backend && pytest tests/ -v --tb=short
```

Expected: all previously passing tests still pass, plus `test_guards.py` (22 tests).

### Step 12: Commit

```bash
git add backend/app/schemas/convoy.py backend/app/api/routes/convoys.py
git commit -m "feat: expand convoy access to org members with role guards"
```

---

## Task 3: `vehicles.py`

**Files:**
- Modify: `backend/app/api/routes/vehicles.py`

### Step 1: Add imports

Add to the top of `vehicles.py` after `from sqlalchemy import select`:

```python
from sqlalchemy import select, or_
```

Add to the import block:

```python
from app.api.guards import get_vehicle_access
from app.models.organization import UserOrganization
```

### Step 2: Expand `list_vehicles` query

Replace the current body of `list_vehicles`:

```python
@router.get("/", response_model=list[VehicleResponse])
async def list_vehicles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    owner_ids_in_shared_orgs = (
        select(UserOrganization.user_id)
        .where(
            UserOrganization.organization_id.in_(
                select(UserOrganization.organization_id)
                .where(UserOrganization.user_id == current_user.id)
            )
        )
        .scalar_subquery()
    )
    result = await db.execute(
        select(Vehicle)
        .where(
            or_(
                Vehicle.owner_id == current_user.id,
                Vehicle.owner_id.in_(owner_ids_in_shared_orgs),
            )
        )
        .order_by(Vehicle.order_index)
    )
    return result.scalars().all()
```

### Step 3: Update `get_vehicle`

Replace the body of `get_vehicle`:

```python
@router.get("/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(
    vehicle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await get_vehicle_access(vehicle_id, current_user, db, require="read")
```

### Step 4: Update `update_vehicle`

Replace the body of `update_vehicle`:

```python
@router.put("/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle(
    vehicle_id: uuid.UUID,
    data: VehicleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vehicle = await get_vehicle_access(vehicle_id, current_user, db, require="write")
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(vehicle, key, value)
    await db.commit()
    await db.refresh(vehicle)
    return vehicle
```

### Step 5: Update `delete_vehicle`

Replace the body of `delete_vehicle`:

```python
@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vehicle(
    vehicle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vehicle = await get_vehicle_access(vehicle_id, current_user, db, require="delete")
    await db.delete(vehicle)
    await db.commit()
```

### Step 6: Run tests

```bash
cd backend && pytest tests/ -v --tb=short
```

Expected: all tests pass.

### Step 7: Commit

```bash
git add backend/app/api/routes/vehicles.py
git commit -m "feat: expand vehicle list to org members, add role guards to read/write/delete"
```

---

## Task 4: `tracking.py`

**Files:**
- Modify: `backend/app/api/routes/tracking.py`

### Step 1: Add import

Add to the imports in `tracking.py`:

```python
from app.api.guards import get_convoy_access
```

### Step 2: Update `get_positions`

Replace `await _assert_convoy_access(convoy_id, current_user.id, db)` with:

```python
await get_convoy_access(convoy_id, current_user, db, require="read")
```

### Step 3: Update `update_position`

Replace `await _assert_convoy_access(convoy_id, current_user.id, db)` with:

```python
await get_convoy_access(convoy_id, current_user, db, require="fahrer")
```

### Step 4: Update `update_vehicle_status`

Replace `await _assert_convoy_access(convoy_id, current_user.id, db)` with:

```python
await get_convoy_access(convoy_id, current_user, db, require="fahrer")
```

### Step 5: Remove `_assert_convoy_access`

Delete the entire `_assert_convoy_access` function at the bottom of `tracking.py` (the function starting at line 185):

```python
# DELETE this entire function:
async def _assert_convoy_access(convoy_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession):
    result = await db.execute(
        select(Convoy).where(Convoy.id == convoy_id, Convoy.owner_id == user_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Convoy nicht gefunden")
```

### Step 6: Run tests

```bash
cd backend && pytest tests/ -v --tb=short
```

Expected: all tests pass.

### Step 7: Commit

```bash
git add backend/app/api/routes/tracking.py
git commit -m "feat: apply org role guards to tracking endpoints (read=beobachter, fahrer=status/position)"
```
