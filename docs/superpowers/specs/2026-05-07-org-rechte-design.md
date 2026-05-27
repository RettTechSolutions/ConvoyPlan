# Org-Rechte Design

**Goal:** Enforce the existing four-tier org role model (`admin | planer | fahrer | beobachter`) so that org membership actually controls who can see and modify convoys, vehicles, and tracking status.

**Architecture:** New `guards.py` module with two guard functions (`get_convoy_access`, `get_vehicle_access`). List queries in `convoys.py` and `vehicles.py` are expanded to include org-accessible objects. Tracking status update gets a minimum-role check. No schema changes — roles and `organization_id` already exist.

**Tech Stack:** FastAPI, SQLAlchemy async, existing `UserOrganization` model.

---

## Permission Matrix

| Action | beobachter | fahrer | planer | admin |
|---|---|---|---|---|
| See org convoys | ✅ | ✅ | ✅ | ✅ |
| Edit org convoys (waypoints, vehicles, route) | ❌ | ❌ | ✅ | ✅ |
| Create convoys in org | ❌ | ❌ | ✅ | ✅ |
| Delete org convoys | ❌ | ❌ | ❌ | ✅ |
| See org vehicles | ✅ | ✅ | ✅ | ✅ |
| Edit org vehicles | ❌ | ❌ | ✅ | ✅ |
| Delete org vehicles | ❌ | ❌ | ❌ | ✅ |
| Update own vehicle tracking status | ❌ | ✅ | ✅ | ✅ |
| Manage org members | ❌ | ❌ | ❌ | ✅ |

Convoy/vehicle owners always have full access to their own objects regardless of org role.

---

## Architecture

### New file: `backend/app/api/guards.py`

Two guard functions used by convoy and vehicle endpoints:

```python
async def get_convoy_access(
    convoy_id: UUID,
    user: User,
    db: AsyncSession,
    require: Literal["read", "write", "delete"] = "read",
) -> Convoy:
    ...

async def get_vehicle_access(
    vehicle_id: UUID,
    user: User,
    db: AsyncSession,
    require: Literal["read", "write", "delete"] = "read",
) -> Vehicle:
    ...
```

**Access resolution logic (same for both):**
1. Load the object (404 if not found).
2. If `user.id == object.owner_id` → access granted unconditionally.
3. Otherwise look up `UserOrganization` row for `(user_id, org_id_of_object)`.
4. If no membership → 403.
5. Map `require` to minimum role:
   - `read` → any role (`beobachter`, `fahrer`, `planer`, `admin`)
   - `write` → `planer` or `admin`
   - `delete` → `admin` only
6. If user's role is below the required minimum → 403.

Role ordering: `beobachter < fahrer < planer < admin`.

**Vehicle org resolution:** A vehicle belongs to its `owner_id`. To determine the org, look up which orgs that owner shares with the requesting user (i.e., any org where both `vehicle.owner_id` and `user.id` are members).

### Modified: `backend/app/api/routes/convoys.py`

- `_convoy_query(user_id)` expanded to also return convoys whose `organization_id` is in the user's org memberships.
- `_get_owned_convoy` replaced by `get_convoy_access(..., require=...)` calls throughout.
- Convoy creation (`POST /api/convoys/`) checks that if `organization_id` is provided, user has at least `planer` role in that org.

### Modified: `backend/app/api/routes/vehicles.py`

- `list_vehicles` expanded to also return vehicles owned by members of shared orgs.
- Read endpoints (`GET /api/vehicles/{id}`) use `get_vehicle_access(..., require="read")`.
- Write endpoints (`PUT`) use `get_vehicle_access(..., require="write")`.
- Delete endpoint uses `get_vehicle_access(..., require="delete")`.

### Modified: `backend/app/api/routes/tracking.py`

- `PATCH .../vehicles/{vehicle_id}/status` uses `get_convoy_access(..., require="read")` for convoy access, then additionally verifies the user has at least `fahrer` role in the convoy's org (or is the convoy owner) before allowing the status update.

---

## Error Responses

| Condition | HTTP |
|---|---|
| Object not found | 404 |
| Not member of org | 403 `"Not a member of this organisation"` |
| Role too low for action | 403 `"Insufficient role: requires planer"` / `"requires admin"` |
| beobachter tries status update | 403 `"Insufficient role: requires fahrer"` |

---

## Testing

- `test_org_access.py` — new test file covering all role/action combinations:
  - beobachter: can list and read org convoys + vehicles, cannot edit/delete/status
  - fahrer: can read + update own vehicle status, cannot edit convoys
  - planer: can edit org convoys + vehicles, cannot delete
  - admin: full access including delete
  - non-member: 403 on all org resources
  - owner: always full access regardless of role
