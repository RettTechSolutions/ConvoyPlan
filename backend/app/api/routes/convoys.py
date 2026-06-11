import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_org_context, OrgCtx
from app.api.guards import get_convoy_access, ROLE_ORDER
from app.database import get_db
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.vehicle import Vehicle
from app.models.waypoint import Waypoint
from app.schemas.convoy import (
    AddVehicleRequest,
    ConvoyCreate,
    ConvoyResponse,
    ConvoyUpdate,
    ConvoyVehicleReorderItem,
)
from app.schemas.waypoint import WaypointCreate, WaypointReorderItem, WaypointResponse, WaypointUpdate
from app.services import audit
from app.services import geometry as geo_svc

router = APIRouter(prefix="/convoys", tags=["convoys"])


def _convoy_query_for_org(org_id: uuid.UUID):
    return (
        select(Convoy)
        .where(Convoy.organization_id == org_id)
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
        "organization_id": convoy.organization_id,
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


@router.get("/", response_model=list[ConvoyResponse], dependencies=[Depends(get_org_context)])
async def list_convoys(
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    result = await db.execute(
        _convoy_query_for_org(org.id).order_by(Convoy.created_at.desc())
    )
    return [_serialize_convoy(c) for c in result.scalars().all()]


@router.post("/", response_model=ConvoyResponse, status_code=status.HTTP_201_CREATED)
async def create_convoy(
    data: ConvoyCreate,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx

    if ROLE_ORDER.get(role, -1) < ROLE_ORDER["planer"]:
        raise HTTPException(403, "Insufficient role: requires planer")

    convoy_data = data.model_dump(exclude={"start_point", "end_point", "organization_id"})
    convoy = Convoy(**convoy_data, owner_id=user.id, organization_id=org.id)
    if data.start_point:
        convoy.start_point = geo_svc.point_to_wkt(data.start_point.lat, data.start_point.lon)
    if data.end_point:
        convoy.end_point = geo_svc.point_to_wkt(data.end_point.lat, data.end_point.lon)
    db.add(convoy)
    await db.commit()

    await audit.record(
        db, audit.CONVOY_CREATED, request=request, actor_id=user.id,
        actor_email=user.email, org_id=org.id, target_type="convoy",
        target_id=convoy.id, detail={"name": convoy.name},
    )

    result = await db.execute(_convoy_query_for_org(org.id).where(Convoy.id == convoy.id))
    return _serialize_convoy(result.scalar_one())


@router.get("/{convoy_id}", response_model=ConvoyResponse)
async def get_convoy(
    convoy_id: uuid.UUID,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    result = await db.execute(
        _convoy_query_for_org(org.id).where(Convoy.id == convoy_id)
    )
    convoy = result.scalar_one_or_none()
    if not convoy:
        raise HTTPException(status_code=404, detail="Convoy not found")
    if convoy.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Convoy not found")
    return _serialize_convoy(convoy)


@router.put("/{convoy_id}", response_model=ConvoyResponse)
async def update_convoy(
    convoy_id: uuid.UUID,
    data: ConvoyUpdate,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    convoy = await get_convoy_access(convoy_id, user, db, require="write", role=role)
    if convoy.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Convoy not found")

    update_data = data.model_dump(exclude_none=True, exclude={"start_point", "end_point"})
    for key, value in update_data.items():
        setattr(convoy, key, value)
    if data.start_point:
        convoy.start_point = geo_svc.point_to_wkt(data.start_point.lat, data.start_point.lon)
    if data.end_point:
        convoy.end_point = geo_svc.point_to_wkt(data.end_point.lat, data.end_point.lon)
    await db.commit()

    changed = sorted(update_data.keys())
    if data.start_point:
        changed.append("start_point")
    if data.end_point:
        changed.append("end_point")
    await audit.record(
        db, audit.CONVOY_UPDATED, request=request, actor_id=user.id,
        actor_email=user.email, org_id=org.id, target_type="convoy",
        target_id=convoy_id, detail={"name": convoy.name, "changed": changed},
    )

    result = await db.execute(_convoy_query_for_org(org.id).where(Convoy.id == convoy_id))
    return _serialize_convoy(result.scalar_one())


@router.delete("/{convoy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_convoy(
    convoy_id: uuid.UUID,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    convoy = await get_convoy_access(convoy_id, user, db, require="delete", role=role)
    if convoy.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Convoy not found")
    convoy_name = convoy.name
    await db.delete(convoy)
    await db.commit()

    await audit.record(
        db, audit.CONVOY_DELETED, request=request, actor_id=user.id,
        actor_email=user.email, org_id=org.id, target_type="convoy",
        target_id=convoy_id, detail={"name": convoy_name},
    )


# --- Vehicle assignment ---

@router.post("/{convoy_id}/vehicles", status_code=status.HTTP_201_CREATED)
async def add_vehicle_to_convoy(
    convoy_id: uuid.UUID,
    data: AddVehicleRequest,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    convoy = await get_convoy_access(convoy_id, user, db, require="write", role=role)
    if convoy.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Convoy not found")

    # Verify vehicle belongs to the same org (prevent cross-org vehicle
    # assignment). Scope directly via org_id — consistent with vehicles.py and
    # robust when a user is a member of multiple organisations.
    vehicle_result = await db.execute(
        select(Vehicle).where(
            Vehicle.id == data.vehicle_id,
            Vehicle.org_id == org.id,
        )
    )
    if vehicle_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Determine the march position server-side instead of trusting the client.
    # The frontend used to send `convoy_vehicles.length`, which leaves a gap
    # (and never reclaims position 0) once an earlier vehicle is removed — the
    # reported "kein Fahrzeug kann mehr Position 1 einnehmen" bug. Appending at
    # max(position)+1 keeps the order gap-free and intuitive.
    existing_result = await db.execute(
        select(ConvoyVehicle).where(ConvoyVehicle.convoy_id == convoy_id)
    )
    existing_cvs = existing_result.scalars().all()
    if any(cv.vehicle_id == data.vehicle_id for cv in existing_cvs):
        raise HTTPException(status_code=409, detail="Vehicle already in convoy")
    next_position = max((cv.position for cv in existing_cvs), default=-1) + 1

    cv = ConvoyVehicle(
        convoy_id=convoy_id,
        vehicle_id=data.vehicle_id,
        position=next_position,
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
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    convoy = await get_convoy_access(convoy_id, user, db, require="write", role=role)
    if convoy.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Convoy not found")
    await db.execute(
        delete(ConvoyVehicle).where(
            ConvoyVehicle.convoy_id == convoy_id,
            ConvoyVehicle.vehicle_id == vehicle_id,
        )
    )
    await db.flush()

    # Re-compact the remaining positions to 0..n-1 so no gap is left behind
    # (otherwise position 0 / "1." stays permanently vacant after removing the
    # first vehicle).
    remaining_result = await db.execute(
        select(ConvoyVehicle)
        .where(ConvoyVehicle.convoy_id == convoy_id)
        .order_by(ConvoyVehicle.position)
    )
    for idx, cv in enumerate(remaining_result.scalars().all()):
        cv.position = idx
    await db.commit()


@router.patch("/{convoy_id}/vehicles/reorder", response_model=ConvoyResponse)
async def reorder_convoy_vehicles(
    convoy_id: uuid.UUID,
    items: list[ConvoyVehicleReorderItem],
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Reorder the march sequence (Marschfolge) of vehicles in a convoy."""
    user, org, role = ctx
    convoy = await get_convoy_access(convoy_id, user, db, require="write", role=role)
    if convoy.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Convoy not found")

    result = await db.execute(
        select(ConvoyVehicle).where(ConvoyVehicle.convoy_id == convoy_id)
    )
    by_vehicle = {cv.vehicle_id: cv for cv in result.scalars().all()}

    if len(items) != len(by_vehicle):
        raise HTTPException(
            status_code=400,
            detail=f"Expected {len(by_vehicle)} vehicles, got {len(items)}",
        )
    if len({i.vehicle_id for i in items}) != len(items):
        raise HTTPException(status_code=400, detail="Duplicate vehicle_id values in request")
    if len({i.position for i in items}) != len(items):
        raise HTTPException(status_code=400, detail="Duplicate position values in request")
    if any(i.vehicle_id not in by_vehicle for i in items):
        raise HTTPException(status_code=400, detail="Unknown vehicle_id in request")

    for item in items:
        by_vehicle[item.vehicle_id].position = item.position
    await db.commit()

    refreshed = await db.execute(_convoy_query_for_org(org.id).where(Convoy.id == convoy_id))
    return _serialize_convoy(refreshed.scalar_one())


# --- Waypoints ---

@router.get("/{convoy_id}/waypoints", response_model=list[WaypointResponse])
async def list_waypoints(
    convoy_id: uuid.UUID,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    convoy = await get_convoy_access(convoy_id, user, db, require="read", role=role)
    if convoy.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Convoy not found")
    result = await db.execute(
        select(Waypoint).where(Waypoint.convoy_id == convoy_id).order_by(Waypoint.order_index)
    )
    waypoints = result.scalars().all()
    return [{**w.__dict__, **geo_svc.waypoint_coords(w)} for w in waypoints]


@router.post("/{convoy_id}/waypoints", response_model=WaypointResponse, status_code=status.HTTP_201_CREATED)
async def create_waypoint(
    convoy_id: uuid.UUID,
    data: WaypointCreate,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    convoy = await get_convoy_access(convoy_id, user, db, require="write", role=role)
    if convoy.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Convoy not found")
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
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    convoy = await get_convoy_access(convoy_id, user, db, require="write", role=role)
    if convoy.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Convoy not found")
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
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    convoy = await get_convoy_access(convoy_id, user, db, require="write", role=role)
    if convoy.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Convoy not found")
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
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    convoy = await get_convoy_access(convoy_id, user, db, require="write", role=role)
    if convoy.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Convoy not found")
    if len({i.order_index for i in items}) != len(items):
        raise HTTPException(status_code=400, detail="Duplicate order_index values in request")
    result = await db.execute(
        select(Waypoint).where(Waypoint.convoy_id == convoy.id)
    )
    existing = {wp.id: wp for wp in result.scalars().all()}

    if len(items) != len(existing):
        raise HTTPException(
            status_code=400,
            detail=f"Expected {len(existing)} waypoints, got {len(items)}",
        )

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


# --- V2: Teilverbände (Sub-Convoys) ---

@router.get("/{convoy_id}/sub-convoys")
async def list_sub_convoys(
    convoy_id: uuid.UUID,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    convoy = await get_convoy_access(convoy_id, user, db, require="read", role=role)
    if convoy.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Convoy not found")
    result = await db.execute(
        _convoy_query_for_org(org.id).where(Convoy.parent_convoy_id == convoy_id)
    )
    return [_serialize_convoy(c) for c in result.scalars().all()]


@router.post("/{convoy_id}/sub-convoys", response_model=ConvoyResponse, status_code=status.HTTP_201_CREATED)
async def create_sub_convoy(
    convoy_id: uuid.UUID,
    data: ConvoyCreate,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    convoy = await get_convoy_access(convoy_id, user, db, require="write", role=role)
    if convoy.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Convoy not found")
    convoy_data = data.model_dump(exclude={"start_point", "end_point", "organization_id"})
    sub = Convoy(**convoy_data, owner_id=user.id, organization_id=org.id, parent_convoy_id=convoy_id)
    if data.start_point:
        sub.start_point = geo_svc.point_to_wkt(data.start_point.lat, data.start_point.lon)
    if data.end_point:
        sub.end_point = geo_svc.point_to_wkt(data.end_point.lat, data.end_point.lon)
    db.add(sub)
    await db.commit()

    await audit.record(
        db, audit.CONVOY_CREATED, request=request, actor_id=user.id,
        actor_email=user.email, org_id=org.id, target_type="convoy",
        target_id=sub.id, detail={"name": sub.name, "parent_convoy_id": str(convoy_id)},
    )

    result = await db.execute(_convoy_query_for_org(org.id).where(Convoy.id == sub.id))
    return _serialize_convoy(result.scalar_one())
