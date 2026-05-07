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
