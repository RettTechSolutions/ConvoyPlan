import json as _json
import uuid
from datetime import timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, File, Query, UploadFile
from fastapi.responses import PlainTextResponse, Response
from shapely.geometry import LineString
from geoalchemy2.shape import from_shape
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.api.guards import get_convoy_access
from app.database import get_db
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.route import Route
from app.models.user import User
from app.models.waypoint import Waypoint
from app.schemas.route import RouteResponse
from app.services import geometry as geo_svc
from app.services import routing as routing_svc
from app.services import schedule as schedule_svc
from app.services import export as export_svc
from app.services import pdf as pdf_svc
from app.services import fuel as fuel_svc
from app.services import overpass as overpass_svc
from app.services import importer as importer_svc

router = APIRouter(prefix="/convoys", tags=["routing"])

_MAX_IMPORT_SIZE = 5 * 1024 * 1024  # 5 MB


def _safe_filename(name: str) -> str:
    """Strip characters that would break a Content-Disposition filename value."""
    return name.replace('"', "").replace("\r", "").replace("\n", "").replace("\0", "")


async def _apply_import(
    convoy_id: uuid.UUID,
    result: importer_svc.ImportResult,
    mode: str,
    db: AsyncSession,
) -> dict:
    try:
        if mode == "replace":
            await db.execute(delete(Waypoint).where(Waypoint.convoy_id == convoy_id))
            start_index = 0
        else:
            max_res = await db.execute(
                select(func.max(Waypoint.order_index)).where(Waypoint.convoy_id == convoy_id)
            )
            max_val = max_res.scalar_one_or_none()
            start_index = (max_val + 1) if max_val is not None else 0

        for i, wp in enumerate(result.waypoints):
            db.add(Waypoint(
                convoy_id=convoy_id,
                name=wp["name"],
                type="waypoint",
                location=geo_svc.point_to_wkt(wp["lat"], wp["lon"]),
                notes=wp["notes"],
                order_index=start_index + i,
            ))

        route_stored = False
        if result.route_coords and len(result.route_coords) >= 2:
            line = LineString(result.route_coords)
            existing = await db.execute(select(Route).where(Route.convoy_id == convoy_id))
            route = existing.scalar_one_or_none()
            if route:
                route.geometry = from_shape(line, srid=4326)
                route.distance_m = None
                route.duration_s = None
            else:
                db.add(Route(
                    convoy_id=convoy_id,
                    geometry=from_shape(line, srid=4326),
                    distance_m=None,
                    duration_s=None,
                ))
            route_stored = True

        await db.commit()
        return {"waypoints_imported": len(result.waypoints), "route_stored": route_stored}
    except Exception:
        await db.rollback()
        raise


async def _load_convoy(
    convoy_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    require: Literal["read", "fahrer", "write", "delete"] = "read",
) -> Convoy:
    await get_convoy_access(convoy_id, user, db, require=require)
    result = await db.execute(
        select(Convoy)
        .where(Convoy.id == convoy_id)
        .options(
            selectinload(Convoy.waypoints),
            selectinload(Convoy.convoy_vehicles).selectinload(ConvoyVehicle.vehicle),
        )
    )
    convoy = result.scalar_one_or_none()
    if not convoy:
        raise HTTPException(status_code=404, detail="Convoy not found")
    return convoy


async def _compute_kanalwechsel(
    db: AsyncSession,
    route_line,  # shapely LineString
    distance_m: int,
    org_id: uuid.UUID | None = None,
) -> list[dict]:
    from app.models.leitstelle import Leitstelle
    from geoalchemy2.shape import from_shape
    from sqlalchemy import or_
    route_geom = from_shape(route_line, srid=4326)

    # Nur global sichtbare Leitstellen sowie die eigenen der jeweiligen
    # Organisation berücksichtigen.
    rows = await db.execute(
        select(
            Leitstelle.id,
            Leitstelle.name,
            Leitstelle.anrufgruppe,
            func.ST_AsGeoJSON(
                func.ST_CollectionExtract(
                    func.ST_Intersection(route_geom, func.ST_Boundary(Leitstelle.geometry)),
                    1,  # 1 = extract Points only
                )
            ).label("crossing_geojson"),
        )
        .where(
            Leitstelle.geometry.isnot(None),
            or_(Leitstelle.org_id.is_(None), Leitstelle.org_id == org_id),
            func.ST_Intersects(route_geom, Leitstelle.geometry),
        )
    )

    entries: list[dict] = []
    for row in rows.all():
        if not row.crossing_geojson:
            continue
        crossing = _json.loads(row.crossing_geojson)
        if crossing["type"] == "Point":
            pts: list[list[float]] = [crossing["coordinates"]]
        elif crossing["type"] == "MultiPoint":
            pts = crossing["coordinates"]
        else:
            continue

        for lon, lat in pts:
            frac_res = await db.execute(
                select(
                    func.ST_LineLocatePoint(
                        route_geom,
                        func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326),
                    )
                )
            )
            frac = frac_res.scalar()
            if frac is None:
                continue
            entries.append({
                "km": round((distance_m / 1000) * frac, 1),
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "leitstelle_id": str(row.id),
                "leitstelle_name": row.name,
                "anrufgruppe": row.anrufgruppe,
            })

    entries.sort(key=lambda x: x["km"])
    return entries


@router.get("/{convoy_id}/route", response_model=RouteResponse | None)
async def get_route(
    convoy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _load_convoy(convoy_id, current_user, db, require="read")
    result = await db.execute(select(Route).where(Route.convoy_id == convoy_id))
    route = result.scalar_one_or_none()
    if not route:
        return None
    geojson = geo_svc.linestring_to_geojson(route.geometry)
    return RouteResponse(
        id=route.id,
        convoy_id=convoy_id,
        distance_m=route.distance_m,
        duration_s=route.duration_s,
        routing_params=route.routing_params,
        geojson=geojson,
        kanalwechsel=route.kanalwechsel or [],
    )


@router.post("/{convoy_id}/calculate-route", response_model=RouteResponse)
async def calculate_route(
    convoy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convoy = await _load_convoy(convoy_id, current_user, db, require="write")

    start = geo_svc.wkb_to_point(convoy.start_point)
    end = geo_svc.wkb_to_point(convoy.end_point)
    if not start or not end:
        raise HTTPException(status_code=400, detail="Convoy start/end point not set")

    points = [start]
    for wp in sorted(convoy.waypoints, key=lambda w: w.order_index):
        coords = geo_svc.waypoint_coords(wp)
        if coords["lat"] and coords["lon"]:
            points.append({"lat": coords["lat"], "lon": coords["lon"]})
    points.append(end)

    # Determine worst-case vehicle constraints
    vehicle_params = {}
    for cv in convoy.convoy_vehicles:
        v = cv.vehicle
        if v.height_cm:
            max_h = vehicle_params.get("max_height_m", float("inf"))
            vehicle_params["max_height_m"] = min(max_h, v.height_cm / 100)

    try:
        route_data = await routing_svc.calculate_route(
            points,
            vehicle_params or None,
            road_preference=convoy.road_preference,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Routing-Service nicht erreichbar")

    coords = route_data["geometry"].get("coordinates", [])
    convoy_duration_s = routing_svc.convoy_duration_s(
        route_data["distance_m"],
        coords,
        route_data.get("road_class_details", []),
        convoy.speed_urban_kmh,
        convoy.speed_rural_kmh,
        max_speed_details=route_data.get("max_speed_details", []),
    )

    # Persist route
    line = LineString(coords)
    existing = await db.execute(select(Route).where(Route.convoy_id == convoy_id))
    route = existing.scalar_one_or_none()
    if route:
        route.geometry = from_shape(line, srid=4326)
        route.distance_m = route_data["distance_m"]
        route.duration_s = convoy_duration_s
        route.routing_params = vehicle_params
    else:
        route = Route(
            convoy_id=convoy_id,
            geometry=from_shape(line, srid=4326),
            distance_m=route_data["distance_m"],
            duration_s=convoy_duration_s,
            routing_params=vehicle_params,
        )
        db.add(route)

    # Calculate waypoint schedule
    if convoy.start_time and convoy.waypoints:
        waypoints_sorted = sorted(convoy.waypoints, key=lambda w: w.order_index)
        n_segments = len(waypoints_sorted) + 1
        seg_duration = convoy_duration_s // n_segments
        schedule = schedule_svc.calculate_schedule(
            waypoints_sorted,
            convoy.start_time.replace(tzinfo=timezone.utc) if convoy.start_time.tzinfo is None else convoy.start_time,
            [seg_duration] * (len(waypoints_sorted)),
        )
        for item in schedule:
            result = await db.execute(select(Waypoint).where(Waypoint.id == item["waypoint_id"]))
            wp = result.scalar_one_or_none()
            if wp:
                wp.planned_arrival = item["planned_arrival"]
                wp.planned_departure = item["planned_departure"]

    await db.commit()
    await db.refresh(route)

    # Re-sort waypoints by their projected position along the route geometry
    route_coords = route_data["geometry"].get("coordinates", [])
    if route_coords and convoy.waypoints:
        from app.services import geometry as _geo
        projected: list[tuple[float, object]] = []
        for wp in convoy.waypoints:
            c = _geo.waypoint_coords(wp)
            if c["lat"] is not None and c["lon"] is not None:
                d = fuel_svc.project_onto_route(route_coords, c["lat"], c["lon"])
                projected.append((d, wp))
        projected.sort(key=lambda x: x[0])
        for new_idx, (_, wp) in enumerate(projected):
            wp.order_index = new_idx
        await db.commit()

    # Kanalwechsel computation
    kanalwechsel = await _compute_kanalwechsel(db, line, route_data["distance_m"], convoy.organization_id)
    route.kanalwechsel = kanalwechsel
    await db.commit()

    # Fuel analysis
    fuel_analysis = fuel_svc.analyse_fuel(
        convoy.convoy_vehicles,
        route_data["distance_m"],
        route_coords,
        route_duration_s=convoy_duration_s,
    )

    return {
        "id": route.id,
        "convoy_id": route.convoy_id,
        "distance_m": route.distance_m,
        "duration_s": route.duration_s,
        "routing_params": route.routing_params,
        "geojson": route_data["geometry"],
        "fuel_analysis": fuel_analysis,
        "kanalwechsel": kanalwechsel,
    }


@router.get("/{convoy_id}/export/gpx")
async def export_gpx(
    convoy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convoy = await _load_convoy(convoy_id, current_user, db, require="read")
    route_result = await db.execute(select(Route).where(Route.convoy_id == convoy_id))
    route = route_result.scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=404, detail="No route calculated yet")

    line = geo_svc.linestring_to_geojson(route.geometry)
    coords = line["coordinates"] if line else []
    waypoints = [
        {**geo_svc.waypoint_coords(w), "name": w.name, "notes": w.notes}
        for w in convoy.waypoints
    ]
    gpx_content = export_svc.build_gpx(convoy.name, waypoints, coords)

    return PlainTextResponse(
        content=gpx_content,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{_safe_filename(convoy.name)}.gpx"'},
    )


@router.get("/{convoy_id}/export/json")
async def export_json(
    convoy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convoy = await _load_convoy(convoy_id, current_user, db, require="read")
    waypoints = [
        {**geo_svc.waypoint_coords(w), "name": w.name, "type": w.type, "notes": w.notes,
         "planned_arrival": w.planned_arrival.isoformat() if w.planned_arrival else None,
         "planned_departure": w.planned_departure.isoformat() if w.planned_departure else None,
         "hold_duration_min": w.hold_duration_min}
        for w in convoy.waypoints
    ]
    vehicles = [
        {"name": cv.vehicle.name, "callsign": cv.vehicle.callsign,
         "license_plate": cv.vehicle.license_plate, "position": cv.position}
        for cv in convoy.convoy_vehicles
    ]
    json_content = export_svc.build_json_export(convoy, waypoints, vehicles)
    return PlainTextResponse(
        content=json_content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{_safe_filename(convoy.name)}.json"'},
    )


@router.get("/{convoy_id}/export/pdf")
async def export_pdf(
    convoy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convoy = await _load_convoy(convoy_id, current_user, db, require="read")
    route_result = await db.execute(select(Route).where(Route.convoy_id == convoy_id))
    route = route_result.scalar_one_or_none()

    waypoints = [
        {
            **geo_svc.waypoint_coords(w),
            "name": w.name,
            "type": w.type,
            "notes": w.notes,
            "halt_purpose": getattr(w, "halt_purpose", None),
            "hold_duration_min": w.hold_duration_min,
            "planned_arrival": w.planned_arrival.isoformat() if w.planned_arrival else None,
            "planned_departure": w.planned_departure.isoformat() if w.planned_departure else None,
        }
        for w in convoy.waypoints
    ]
    vehicles = [
        {
            "name": cv.vehicle.name,
            "callsign": cv.vehicle.callsign,
            "license_plate": cv.vehicle.license_plate,
            "height_cm": cv.vehicle.height_cm,
            "weight_kg": cv.vehicle.weight_kg,
            "convoy_role": cv.vehicle.convoy_role,
            "position": cv.position,
            "sonderfunktion": cv.sonderfunktion,
            "mobile_phone": cv.mobile_phone,
        }
        for cv in convoy.convoy_vehicles
    ]

    kanalwechsel = route.kanalwechsel if route else None
    pdf_bytes = pdf_svc.generate_marschbefehl(convoy, waypoints, vehicles, route, kanalwechsel)
    filename = f"Marschbefehl_{_safe_filename(convoy.name).replace(' ', '_')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{convoy_id}/import/gpx")
async def import_gpx(
    convoy_id: uuid.UUID,
    mode: Literal["add", "replace"] = Query(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_convoy_access(convoy_id, current_user, db, require="write")
    content = await file.read()
    if len(content) > _MAX_IMPORT_SIZE:
        raise HTTPException(status_code=413, detail="Datei zu groß (max 5 MB)")
    try:
        result = importer_svc.parse_gpx(content)
    except ValueError:
        raise HTTPException(status_code=422, detail="Ungültige GPX-Datei")
    return await _apply_import(convoy_id, result, mode, db)


@router.post("/{convoy_id}/import/geojson")
async def import_geojson(
    convoy_id: uuid.UUID,
    mode: Literal["add", "replace"] = Query(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_convoy_access(convoy_id, current_user, db, require="write")
    content = await file.read()
    if len(content) > _MAX_IMPORT_SIZE:
        raise HTTPException(status_code=413, detail="Datei zu groß (max 5 MB)")
    try:
        result = importer_svc.parse_geojson(content)
    except ValueError:
        raise HTTPException(status_code=422, detail="Ungültige GeoJSON-Datei")
    return await _apply_import(convoy_id, result, mode, db)


@router.get("/{convoy_id}/fuel-stations")
async def find_fuel_stations(
    convoy_id: uuid.UUID,
    lat: float,
    lon: float,
    radius_m: int = 3000,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Find fuel stations near (lat, lon) – typically the recommended stop position."""
    await _load_convoy(convoy_id, current_user, db, require="read")
    stations = await overpass_svc.find_fuel_stations(lat, lon, radius_m)
    return stations


# Public share endpoint
@router.get("/share/{token}", tags=["share"])
async def get_shared_convoy(token: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Convoy)
        .where(Convoy.share_token == token)
        .options(
            selectinload(Convoy.waypoints),
            selectinload(Convoy.convoy_vehicles).selectinload(ConvoyVehicle.vehicle),
        )
    )
    convoy = result.scalar_one_or_none()
    if not convoy:
        raise HTTPException(status_code=404, detail="Not found")

    route_result = await db.execute(select(Route).where(Route.convoy_id == convoy.id))
    route = route_result.scalar_one_or_none()

    return {
        "name": convoy.name,
        "organization": convoy.organization,
        "start_time": convoy.start_time,
        "waypoints": [
            {**geo_svc.waypoint_coords(w), "name": w.name, "type": w.type,
             "planned_arrival": w.planned_arrival, "planned_departure": w.planned_departure}
            for w in convoy.waypoints
        ],
        "geojson": geo_svc.linestring_to_geojson(route.geometry) if route else None,
    }
