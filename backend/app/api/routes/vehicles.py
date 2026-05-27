import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_org_context, OrgCtx
from app.database import get_db
from app.models.vehicle import Vehicle
from app.schemas.vehicle import VehicleCreate, VehicleResponse, VehicleUpdate

router = APIRouter(prefix="/vehicles", tags=["vehicles"])

ROLE_ORDER = {"beobachter": 0, "fahrer": 1, "planer": 2, "admin": 3}


def _require_min_role(role: str, minimum: str) -> None:
    if ROLE_ORDER.get(role, -1) < ROLE_ORDER[minimum]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


@router.get("/", response_model=list[VehicleResponse])
async def list_vehicles(
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    # Fahrzeuge direkt per org_id filtern — verhindert Leakage wenn User in mehreren Orgs ist
    result = await db.execute(
        select(Vehicle)
        .where(Vehicle.org_id == org.id)
        .order_by(Vehicle.order_index)
    )
    return result.scalars().all()


class ReorderItem(BaseModel):
    id: uuid.UUID
    order_index: int


@router.patch("/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_vehicles(
    items: list[ReorderItem],
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    ids = [item.id for item in items]
    # owner_id check is intentional: reordering is a personal UI preference, not an org action
    result = await db.execute(
        select(Vehicle).where(Vehicle.id.in_(ids), Vehicle.owner_id == user.id)
    )
    vehicles = {v.id: v for v in result.scalars().all()}
    for item in items:
        if item.id in vehicles:
            vehicles[item.id].order_index = item.order_index
    await db.commit()


@router.post("/", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
async def create_vehicle(
    data: VehicleCreate,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    vehicle = Vehicle(**data.model_dump(), owner_id=user.id, org_id=org.id)
    db.add(vehicle)
    await db.commit()
    await db.refresh(vehicle)
    return vehicle


async def _get_org_vehicle(vehicle_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession) -> Vehicle:
    """Fetch vehicle by ID, scoped directly to the org via org_id."""
    result = await db.execute(
        select(Vehicle).where(
            Vehicle.id == vehicle_id,
            Vehicle.org_id == org_id,
        )
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    return vehicle


@router.get("/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(
    vehicle_id: uuid.UUID,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    return await _get_org_vehicle(vehicle_id, org.id, db)


@router.put("/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle(
    vehicle_id: uuid.UUID,
    data: VehicleUpdate,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    _require_min_role(role, "planer")
    vehicle = await _get_org_vehicle(vehicle_id, org.id, db)
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(vehicle, key, value)
    await db.commit()
    await db.refresh(vehicle)
    return vehicle


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vehicle(
    vehicle_id: uuid.UUID,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    _require_min_role(role, "planer")
    vehicle = await _get_org_vehicle(vehicle_id, org.id, db)
    await db.delete(vehicle)
    await db.commit()
