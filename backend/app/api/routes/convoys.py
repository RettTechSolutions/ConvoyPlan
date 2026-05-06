import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.database import get_db
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.waypoint import Waypoint
from app.schemas.convoy import AddVehicleRequest, ConvoyCreate, ConvoyResponse, ConvoyUpdate
from app.schemas.waypoint import WaypointCreate, WaypointReorderItem, WaypointResponse, WaypointUpdate
from app.services import geometry as geo_svc

router = APIRouter(prefix="/convoys", tags=["convoys"])


def _convoy_query(owner_id):
    return (
        select(Convoy)
        .where(Convoy.owner_id == owner_id)
        .options(
            selectinload(Convoy.convoy_vehicles).selectinload(ConvoyVehicle.vehicle),
            selectinload(Convoy.waypoints),
        )
    )


def _serialize_convoy(convoy: Convoy) -> dict:
    data = {
        "id": convoy.id,
        "name": convoy.name,
        "organization": convoy.organization,
        "start_time": convoy.start_time,
        "speed_urban_kmh": convoy.speed_urban_kmh,
        "speed_rural_kmh": convoy.speed_rural_kmh,
        "road_preference": convoy.road_preference,
        "spacing_urban_m": convoy.spacing_urban_m,
        "spacing_rural_m": convoy.spacing_rural_m,
        "spacing_motorway_m": convoy.spacing_motorway_m,
        "status": convoy.status,
        "share_token": convoy.share_token,
        "created_at": convoy.created_at,
        "start_point": geo_svc.wkb_to_point(convoy.start_point),
        "end_point": geo_svc.wkb_to_point(convoy.end_point),
        "lage": convoy.lage,
        "auftrag": convoy.auftrag,
        "marschform": convoy.marschform,
        "ablaufpunkt": convoy.ablaufpunkt,
        "ablaufzeit": convoy.ablaufzeit,
        "ablaufführer": convoy.ablaufführer,
        "versorgung": convoy.versorgung,
        "funkgruppe": convoy.funkgruppe,
        "anlagen": convoy.anlagen,
        "convoy_vehicles": [
            {
                "vehicle": cv.vehicle,
                "position": cv.position,
                "vehicle_status": cv.vehicle_status,
                "sonderfunktion": cv.sonderfunktion,
                "mobile_phone": cv.mobile_phone,
            }
            for cv in convoy.convoy_vehicles
        ],
        "waypoints": [
            {**w.__dict__, **geo_svc.waypoint_coords(w)}
            for w in convoy.waypoints
        ],
    }
    return data


@router.get("/", response_model=list[ConvoyResponse])
async def list_convoys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(_convoy_query(current_user.id))
    return [_serialize_convoy(c) for c in result.scalars().all()]


@router.post("/", response_model=ConvoyResponse, status_code=status.HTTP_201_CREATED)
async def create_convoy(
    data: ConvoyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convoy_data = data.model_dump(exclude={"start_point", "end_point"})
    convoy = Convoy(**convoy_data, owner_id=current_user.id)
    if data.start_point:
        convoy.start_point = geo_svc.point_to_wkt(data.start_point.lat, data.start_point.lon)
    if data.end_point:
        convoy.end_point = geo_svc.point_to_wkt(data.end_point.lat, data.end_point.lon)
    db.add(convoy)
    await db.commit()

    result = await db.execute(_convoy_query(current_user.id).where(Convoy.id == convoy.id))
    return _serialize_convoy(result.scalar_one())


@router.get("/{convoy_id}", response_model=ConvoyResponse)
async def get_convoy(
    convoy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        _convoy_query(current_user.id).where(Convoy.id == convoy_id)
    )
    convoy = result.scalar_one_or_none()
    if not convoy:
        raise HTTPException(status_code=404, detail="Convoy not found")
    return _serialize_convoy(convoy)


@router.put("/{convoy_id}", response_model=ConvoyResponse)
async def update_convoy(
    convoy_id: uuid.UUID,
    data: ConvoyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        _convoy_query(current_user.id).where(Convoy.id == convoy_id)
    )
    convoy = result.scalar_one_or_none()
    if not convoy:
        raise HTTPException(status_code=404, detail="Convoy not found")

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


@router.delete("/{convoy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_convoy(
    convoy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Convoy).where(Convoy.id == convoy_id, Convoy.owner_id == current_user.id)
    )
    convoy = result.scalar_one_or_none()
    if not convoy:
        raise HTTPException(status_code=404, detail="Convoy not found")
    await db.delete(convoy)
    await db.commit()


# --- Vehicle assignment ---

@router.post("/{convoy_id}/vehicles", status_code=status.HTTP_201_CREATED)
async def add_vehicle_to_convoy(
    convoy_id: uuid.UUID,
    data: AddVehicleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convoy = await _get_owned_convoy(convoy_id, current_user.id, db)
    vehicle_result = await db.execute(
        select(Vehicle).where(Vehicle.id == data.vehicle_id, Vehicle.owner_id == current_user.id)
    )
    if not vehicle_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Vehicle not found")

    cv = ConvoyVehicle(
        convoy_id=convoy_id,
        vehicle_id=data.vehicle_id,
        position=data.position,
        sonderfunktion=data.sonderfunktion,
        mobile_phone=data.mobile_phone,
    )
    db.add(cv)
    await db.commit()
    return {"status": "added"}


@router.delete("/{convoy_id}/vehicles/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_vehicle_from_convoy(
    convoy_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_convoy(convoy_id, current_user.id, db)
    await db.execute(
        delete(ConvoyVehicle).where(
            ConvoyVehicle.convoy_id == convoy_id,
            ConvoyVehicle.vehicle_id == vehicle_id,
        )
    )
    await db.commit()


# --- Waypoints ---

@router.get("/{convoy_id}/waypoints", response_model=list[WaypointResponse])
async def list_waypoints(
    convoy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_convoy(convoy_id, current_user.id, db)
    result = await db.execute(
        select(Waypoint).where(Waypoint.convoy_id == convoy_id).order_by(Waypoint.order_index)
    )
    waypoints = result.scalars().all()
    return [{**w.__dict__, **geo_svc.waypoint_coords(w)} for w in waypoints]


@router.post("/{convoy_id}/waypoints", response_model=WaypointResponse, status_code=status.HTTP_201_CREATED)
async def create_waypoint(
    convoy_id: uuid.UUID,
    data: WaypointCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_convoy(convoy_id, current_user.id, db)
    wp_data = data.model_dump(exclude={"lat", "lon"})
    wp = Waypoint(**wp_data, convoy_id=convoy_id)
    wp.location = geo_svc.point_to_wkt(data.lat, data.lon)
    db.add(wp)
    await db.commit()
    await db.refresh(wp)
    return {**wp.__dict__, **geo_svc.waypoint_coords(wp)}


@router.put("/{convoy_id}/waypoints/{waypoint_id}", response_model=WaypointResponse)
async def update_waypoint(
    convoy_id: uuid.UUID,
    waypoint_id: uuid.UUID,
    data: WaypointUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_convoy(convoy_id, current_user.id, db)
    result = await db.execute(
        select(Waypoint).where(Waypoint.id == waypoint_id, Waypoint.convoy_id == convoy_id)
    )
    wp = result.scalar_one_or_none()
    if not wp:
        raise HTTPException(status_code=404, detail="Waypoint not found")
    update_data = data.model_dump(exclude_none=True, exclude={"lat", "lon"})
    for key, value in update_data.items():
        setattr(wp, key, value)
    if data.lat is not None and data.lon is not None:
        wp.location = geo_svc.point_to_wkt(data.lat, data.lon)
    await db.commit()
    await db.refresh(wp)
    return {**wp.__dict__, **geo_svc.waypoint_coords(wp)}


@router.delete("/{convoy_id}/waypoints/{waypoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_waypoint(
    convoy_id: uuid.UUID,
    waypoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_convoy(convoy_id, current_user.id, db)
    result = await db.execute(
        select(Waypoint).where(Waypoint.id == waypoint_id, Waypoint.convoy_id == convoy_id)
    )
    wp = result.scalar_one_or_none()
    if not wp:
        raise HTTPException(status_code=404, detail="Waypoint not found")
    await db.delete(wp)
    await db.commit()


@router.patch("/{convoy_id}/waypoints/reorder", response_model=list[WaypointResponse])
async def reorder_waypoints(
    convoy_id: uuid.UUID,
    items: list[WaypointReorderItem],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    convoy = await _get_owned_convoy(convoy_id, current_user.id, db)
    result = await db.execute(
        select(Waypoint).where(Waypoint.convoy_id == convoy.id)
    )
    existing = {wp.id: wp for wp in result.scalars().all()}

    for item in items:
        if item.id not in existing:
            raise HTTPException(status_code=404, detail=f"Waypoint {item.id} not found in convoy")
        existing[item.id].order_index = item.order_index

    await db.commit()

    result2 = await db.execute(
        select(Waypoint)
        .where(Waypoint.convoy_id == convoy.id)
        .order_by(Waypoint.order_index)
    )
    waypoints = result2.scalars().all()
    return [{**w.__dict__, **geo_svc.waypoint_coords(w)} for w in waypoints]


async def _get_owned_convoy(convoy_id: uuid.UUID, owner_id: uuid.UUID, db: AsyncSession) -> Convoy:
    result = await db.execute(
        select(Convoy).where(Convoy.id == convoy_id, Convoy.owner_id == owner_id)
    )
    convoy = result.scalar_one_or_none()
    if not convoy:
        raise HTTPException(status_code=404, detail="Convoy not found")
    return convoy


# --- V2: Teilverbände (Sub-Convoys) ---

@router.get("/{convoy_id}/sub-convoys")
async def list_sub_convoys(
    convoy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_convoy(convoy_id, current_user.id, db)
    result = await db.execute(
        _convoy_query(current_user.id).where(Convoy.parent_convoy_id == convoy_id)
    )
    return [_serialize_convoy(c) for c in result.scalars().all()]


@router.post("/{convoy_id}/sub-convoys", response_model=ConvoyResponse, status_code=status.HTTP_201_CREATED)
async def create_sub_convoy(
    convoy_id: uuid.UUID,
    data: ConvoyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_convoy(convoy_id, current_user.id, db)
    convoy_data = data.model_dump(exclude={"start_point", "end_point"})
    sub = Convoy(**convoy_data, owner_id=current_user.id, parent_convoy_id=convoy_id)
    if data.start_point:
        sub.start_point = geo_svc.point_to_wkt(data.start_point.lat, data.start_point.lon)
    if data.end_point:
        sub.end_point = geo_svc.point_to_wkt(data.end_point.lat, data.end_point.lon)
    db.add(sub)
    await db.commit()

    result = await db.execute(_convoy_query(current_user.id).where(Convoy.id == sub.id))
    return _serialize_convoy(result.scalar_one())
