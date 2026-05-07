import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.guards import get_vehicle_access
from app.database import get_db
from app.models.organization import UserOrganization
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.vehicle import VehicleCreate, VehicleResponse, VehicleUpdate

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


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


class ReorderItem(BaseModel):
    id: uuid.UUID
    order_index: int


@router.patch("/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_vehicles(
    items: list[ReorderItem],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ids = [item.id for item in items]
    result = await db.execute(
        select(Vehicle).where(Vehicle.id.in_(ids), Vehicle.owner_id == current_user.id)
    )
    vehicles = {v.id: v for v in result.scalars().all()}
    for item in items:
        if item.id in vehicles:
            vehicles[item.id].order_index = item.order_index
    await db.commit()


@router.post("/", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
async def create_vehicle(
    data: VehicleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vehicle = Vehicle(**data.model_dump(), owner_id=current_user.id)
    db.add(vehicle)
    await db.commit()
    await db.refresh(vehicle)
    return vehicle


@router.get("/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(
    vehicle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await get_vehicle_access(vehicle_id, current_user, db, require="read")


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


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vehicle(
    vehicle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vehicle = await get_vehicle_access(vehicle_id, current_user, db, require="delete")
    await db.delete(vehicle)
    await db.commit()
