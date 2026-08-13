import asyncio
import json as _json
import logging
import re
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, File, Query, UploadFile
from fastapi.responses import PlainTextResponse, Response
from shapely.geometry import LineString
from geoalchemy2.shape import from_shape
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.api.guards import get_convoy_access
from app.api.quota import routing_quota
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/convoys", tags=["routing"])


# Strip control characters (CWE-113 header injection), quote/backslash and path
# separators that would break a quoted Content-Disposition filename (RFC 6266).
_UNSAFE_FILENAME_RE = re.compile(r'[\x00-\x1f\x7f"\\/]')


def _safe_filename(name: str) -> str:
    """Return a header-safe version of *name* for Content-Disposition filenames."""
    return _UNSAFE_FILENAME_RE.sub("_", name)


_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB — guard against DoS via huge uploads


def _out_of_bounds_message(point_index: int | None, total_points: int) -> str:
    """Verständliche Meldung für einen Punkt außerhalb der Kartendaten.

    Die Punktliste ist [Start, *Wegpunkte, Ziel] — der GraphHopper-Index lässt
    sich daher auf Start/Ziel/Wegpunkt abbilden.
    """
    if point_index == 0:
        label = "Der Startpunkt liegt"
    elif point_index is not None and point_index == total_points - 1:
        label = "Das Ziel liegt"
    elif point_index is not None and 0 < point_index < total_points - 1:
        label = f"Wegpunkt {point_index} liegt"
    else:
        label = "Mindestens ein Punkt liegt"
    return (
        f"{label} außerhalb des abgedeckten Kartenbereichs. "
        "Die Routenberechnung ist aktuell auf Deutschland beschränkt — "
        "bitte Start, Ziel und alle Wegpunkte innerhalb Deutschlands wählen."
    )


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


# Glättungs-Parameter für die Kanalwechsel-Berechnung: Routen pendeln an
# Gebietsgrenzen (z. B. Autobahn entlang einer Landkreisgrenze) oft mehrfach
# über die Grenze. Lücken bis KW_MERGE_GAP_KM innerhalb derselben Leitstelle
# gelten daher als durchgehende Abdeckung; Aufenthalte unter
# KW_MIN_PRESENCE_KM mitten auf der Route als Geometrie-Rauschen.
KW_MERGE_GAP_KM = 5.0
KW_MIN_PRESENCE_KM = 1.0
KW_EDGE_KM = 0.2


async def _compute_kanalwechsel(
    db: AsyncSession,
    route_line,  # shapely LineString
    distance_m: int,
    org_id: uuid.UUID | None = None,
) -> list[dict]:
    """Bestimmt An- und Abmeldepunkte bei Leitstellen entlang der Route.

    Für jede Leitstelle werden die Routenabschnitte ermittelt, die in ihrem
    Zuständigkeitsgebiet liegen. Daraus entsteht eine sequenzielle
    Übergabekette: Der Verband ist zu jedem Zeitpunkt bei genau einer
    Leitstelle angemeldet — bei einem Wechsel wird erst bei der alten
    Leitstelle abgemeldet, dann bei der neuen angemeldet. Überlappen sich
    zwei Gebiete (bzw. pendelt die Route an der Grenze hin und her), liegt
    der Übergabepunkt in der Mitte des gemeinsamen Korridors. Der erste
    Eintrag der Kette ist die Convoy-Anmeldung bei der Start-Leitstelle.
    """
    from app.models.leitstelle import Leitstelle
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point
    from sqlalchemy import or_

    total_km = (distance_m or 0) / 1000
    if total_km <= 0:
        return []
    route_geom = from_shape(route_line, srid=4326)

    # Nur global sichtbare Leitstellen sowie die eigenen der jeweiligen
    # Organisation berücksichtigen.
    rows = await db.execute(
        select(
            Leitstelle.id,
            Leitstelle.name,
            Leitstelle.anrufgruppe,
            Leitstelle.zusatz_kanaele,
            func.ST_AsGeoJSON(
                func.ST_CollectionExtract(
                    func.ST_Intersection(route_geom, Leitstelle.geometry),
                    2,  # 2 = nur LineStrings (Routenabschnitte im Gebiet)
                )
            ).label("covered_geojson"),
        )
        .where(
            Leitstelle.geometry.isnot(None),
            or_(Leitstelle.org_id.is_(None), Leitstelle.org_id == org_id),
            func.ST_Intersects(route_geom, Leitstelle.geometry),
        )
    )

    presences: list[dict] = []
    for row in rows.all():
        if not row.covered_geojson:
            continue
        covered = _json.loads(row.covered_geojson)
        if covered["type"] == "LineString":
            segments: list[list[list[float]]] = [covered["coordinates"]]
        elif covered["type"] == "MultiLineString":
            segments = covered["coordinates"]
        else:
            continue

        # Jeden Abschnitt auf ein km-Intervall entlang der Route abbilden.
        # PostGIS kann leere Geometrien liefern (LINESTRING EMPTY →
        # coordinates: []) wenn sich Route und Gebiet nur tangential berühren —
        # überspringen statt am Entpacken zu scheitern. Z-Koordinaten ignorieren.
        intervals: list[list[float]] = []
        for seg in segments:
            pts = [p for p in seg if p and len(p) >= 2]
            if len(pts) < 2:
                continue
            fracs = [
                route_line.project(Point(p[0], p[1]), normalized=True)
                for p in (pts[0], pts[-1])
            ]
            km_a, km_b = sorted(f * total_km for f in fracs)
            intervals.append([km_a, km_b])
        if not intervals:
            continue

        # Nahe beieinanderliegende Abschnitte zusammenfassen (Grenz-Pendelei).
        intervals.sort()
        merged = [intervals[0]]
        for start, end in intervals[1:]:
            if start - merged[-1][1] <= KW_MERGE_GAP_KM:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])

        for start, end in merged:
            touches_start = start <= KW_EDGE_KM
            touches_end = end >= total_km - KW_EDGE_KM
            if end - start < KW_MIN_PRESENCE_KM and not (touches_start or touches_end):
                continue
            presences.append({
                "start": 0.0 if touches_start else start,
                "end": total_km if touches_end else end,
                "leitstelle_id": str(row.id),
                "leitstelle_name": row.name,
                "anrufgruppe": row.anrufgruppe,
                "zusatz_kanaele": row.zusatz_kanaele or [],
            })

    if not presences:
        return []

    # Sequenzielle Übergabekette aufbauen. Startgebiet zuerst (bei mehreren
    # Kandidaten das mit der längsten Abdeckung), danach in Routenreihenfolge.
    presences.sort(key=lambda p: (p["start"], -(p["end"] - p["start"])))
    events: list[tuple[float, str, dict]] = []
    active = presences[0]
    events.append((active["start"], "convoy_anmeldung", active))
    queue = presences[1:]
    i = 0
    while i < len(queue):
        nxt = queue[i]
        i += 1
        if nxt["start"] <= active["end"]:
            # Gebiete überlappen — Übergabe in der Mitte des Korridors.
            handover = (nxt["start"] + min(active["end"], nxt["end"])) / 2
            events.append((handover, "abmelden", active))
            events.append((handover, "anmelden", nxt))
        else:
            # Lücke ohne Abdeckung: am Gebietsende abmelden, am nächsten
            # Gebietsanfang anmelden.
            events.append((active["end"], "abmelden", active))
            events.append((nxt["start"], "anmelden", nxt))
        if nxt["end"] < active["end"]:
            # Enklave: der Rest des alten Gebiets kommt nach der Enklave
            # wieder an die Reihe.
            rest = {**active, "start": nxt["end"]}
            j = i
            while j < len(queue) and queue[j]["start"] < rest["start"]:
                j += 1
            queue.insert(j, rest)
        active = nxt
    if active["end"] < total_km - KW_EDGE_KM:
        # Route endet außerhalb jedes Leitstellen-Gebiets.
        events.append((active["end"], "abmelden", active))

    entries: list[dict] = []
    for km, typ, pres in events:
        pt = route_line.interpolate(km / total_km, normalized=True)
        entries.append({
            "km": round(km, 1),
            "lat": round(pt.y, 6),
            "lon": round(pt.x, 6),
            "leitstelle_id": pres["leitstelle_id"],
            "leitstelle_name": pres["leitstelle_name"],
            "anrufgruppe": pres["anrufgruppe"],
            "zusatz_kanaele": pres["zusatz_kanaele"],
            "typ": typ,
        })
    # Stabil nach km sortieren — bei gleichem km bleibt die Kettenreihenfolge
    # (erst abmelden, dann anmelden) erhalten.
    entries.sort(key=lambda x: x["km"])
    return entries


@router.get("/{convoy_id}/route", response_model=RouteResponse | None)
async def get_route(
    convoy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convoy = await _load_convoy(convoy_id, current_user, db, require="read")
    result = await db.execute(select(Route).where(Route.convoy_id == convoy_id))
    route = result.scalar_one_or_none()
    if not route:
        return None
    geojson = geo_svc.linestring_to_geojson(route.geometry)

    # Recompute the fuel/duration analysis so a reloaded route shows the same
    # warnings (Tankstopp, technische Halte) as right after calculation.
    fuel_analysis = None
    if route.distance_m is not None:
        route_coords = geojson["coordinates"] if geojson else []
        fuel_analysis = fuel_svc.analyse_fuel(
            convoy.convoy_vehicles,
            route.distance_m,
            route_coords,
            route_duration_s=route.duration_s or 0,
        )

    # Departure + destination ETA, recomputed so a reloaded route shows the same
    # total arrival as right after calculation (drive time + all waypoint holds).
    # Same start_dt basis as the waypoint times → the whole Zeitplan stays consistent.
    route_planned_departure = None
    route_planned_arrival = None
    if convoy.start_time is not None:
        # Work in naive wall-clock (see migration 0029/0030): the schedule times
        # are stored and displayed as the wall-clock the user entered, without a
        # timezone the frontend would re-interpret and shift.
        start_dt = (
            convoy.start_time
            if convoy.start_time.tzinfo is None
            else convoy.start_time.replace(tzinfo=None)
        )
        route_planned_departure = start_dt
        if route.duration_s is not None:
            route_planned_arrival = schedule_svc.destination_arrival(
                start_dt, route.duration_s, convoy.waypoints
            )

    return RouteResponse(
        id=route.id,
        convoy_id=convoy_id,
        distance_m=route.distance_m,
        duration_s=route.duration_s,
        routing_params=route.routing_params,
        geojson=geojson,
        fuel_analysis=fuel_analysis,
        kanalwechsel=route.kanalwechsel or [],
        planned_departure=route_planned_departure,
        planned_arrival=route_planned_arrival,
    )


@router.post(
    "/{convoy_id}/calculate-route",
    response_model=RouteResponse,
    dependencies=[Depends(routing_quota)],
)
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

    # Load any previously stored route up front. Its geometry lets us order the
    # waypoints by their real position along the route before re-routing. The
    # frontend appends recommended Technische Halte / Tankstopps to the END of
    # the waypoint list (highest order_index), even though they physically lie
    # in the middle of the route. Without re-ordering, the router would visit
    # them last and detour back and forth — the reported ~700 km jump on
    # recalculation. Projecting onto the prior route fixes the order so the new
    # route stays clean.
    existing_route = (
        await db.execute(select(Route).where(Route.convoy_id == convoy_id))
    ).scalar_one_or_none()
    prev_coords: list = []
    if existing_route is not None and existing_route.geometry is not None:
        prev_line = geo_svc.linestring_to_geojson(existing_route.geometry)
        prev_coords = (prev_line or {}).get("coordinates", []) if prev_line else []

    positioned: list[tuple[Any, dict]] = []
    for wp in convoy.waypoints:
        coords = geo_svc.waypoint_coords(wp)
        if coords["lat"] is not None and coords["lon"] is not None:
            positioned.append((wp, coords))

    if prev_coords and len(positioned) > 1:
        positioned.sort(
            key=lambda pc: fuel_svc.project_onto_route(prev_coords, pc[1]["lat"], pc[1]["lon"])
        )
    else:
        positioned.sort(key=lambda pc: pc[0].order_index)

    points = [start]
    points.extend({"lat": c["lat"], "lon": c["lon"]} for _, c in positioned)
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
    except routing_svc.RoutingOutOfBoundsError as exc:
        # Punkt außerhalb der geladenen Kartendaten (aktuell nur Deutschland).
        logger.warning("Routing point out of bounds for convoy %s: %s", convoy_id, exc)
        raise HTTPException(status_code=422, detail=_out_of_bounds_message(exc.point_index, len(points)))
    except ValueError as exc:
        # GraphHopper hat geantwortet, aber die Anfrage abgelehnt (z. B. Punkt
        # außerhalb der Kartendaten, fehlende Encoded Values) — Meldung
        # durchreichen, damit der Fehler im Frontend diagnostizierbar ist.
        logger.error("Routing rejected for convoy %s: %s", convoy_id, exc)
        raise HTTPException(status_code=502, detail=f"Routing fehlgeschlagen: {exc}")
    except Exception as exc:
        logger.error("Routing service error for convoy %s: %s", convoy_id, exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Routing-Dienst nicht verfügbar")

    coords = route_data["geometry"].get("coordinates", [])
    if len(coords) < 2:
        logger.error("Routing returned invalid geometry for convoy %s (%d coords)", convoy_id, len(coords))
        raise HTTPException(status_code=502, detail="Routing-Dienst lieferte keine gültige Routengeometrie")
    try:
        convoy_duration_s = routing_svc.convoy_duration_s(
            route_data["distance_m"],
            coords,
            route_data.get("road_class_details", []),
            convoy.speed_urban_kmh,
            convoy.speed_rural_kmh,
            max_speed_details=route_data.get("max_speed_details", []),
        )
    except Exception as exc:
        logger.warning("Duration calculation failed, falling back: %s", exc)
        convoy_duration_s = routing_svc.convoy_duration_s(
            route_data["distance_m"],
            coords,
            route_data.get("road_class_details", []),
            convoy.speed_urban_kmh,
            convoy.speed_rural_kmh,
        )

    # Persist route
    line = LineString(coords)
    route = existing_route
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

    # Order waypoints by their real position along the new route, then build a
    # distance-proportional schedule. Projecting first means both the visiting
    # order and each leg's travel time reflect the actual route: a waypoint's
    # ETA lands at the same fraction of the total drive time as its position
    # along the route. The previous "total ÷ (waypoints + 1)" even split pushed
    # every waypoint towards the middle regardless of distance — e.g. a single
    # waypoint at 40 % of the route was scheduled at 50 % of the drive time.
    route_coords = route_data["geometry"].get("coordinates", [])
    total_distance_m = route_data["distance_m"]
    route_planned_departure = None
    route_planned_arrival = None

    projected: list[tuple[float, Any]] = []
    if route_coords and convoy.waypoints:
        for wp in convoy.waypoints:
            c = geo_svc.waypoint_coords(wp)
            if c["lat"] is not None and c["lon"] is not None:
                d = fuel_svc.project_onto_route(route_coords, c["lat"], c["lon"])
                projected.append((d, wp))
        projected.sort(key=lambda x: x[0])
        for new_idx, (_, wp) in enumerate(projected):
            wp.order_index = new_idx

    if convoy.start_time:
        # Work in naive wall-clock (see migration 0029/0030): the schedule times
        # are stored and displayed as the wall-clock the user entered, without a
        # timezone the frontend would re-interpret and shift.
        start_dt = (
            convoy.start_time
            if convoy.start_time.tzinfo is None
            else convoy.start_time.replace(tzinfo=None)
        )
        route_planned_departure = start_dt
        if projected:
            waypoints_sorted = [wp for _, wp in projected]
            # Per-leg distances along the route: Start→WP1, WP1→WP2, …
            seg_distances: list[float] = []
            prev = 0.0
            for cum, _ in projected:
                seg_distances.append(max(0.0, cum - prev))
                prev = cum
            seg_durations = schedule_svc.split_duration_by_distance(
                convoy_duration_s, seg_distances, total_distance_m
            )
            schedule = schedule_svc.calculate_schedule(waypoints_sorted, start_dt, seg_durations)
            for item, wp in zip(schedule, waypoints_sorted):
                wp.planned_arrival = item["planned_arrival"]
                wp.planned_departure = item["planned_departure"]
        # Arrival at the destination (Ziel): full drive time plus every hold.
        route_planned_arrival = schedule_svc.destination_arrival(
            start_dt, convoy_duration_s, convoy.waypoints
        )

    await db.commit()
    await db.refresh(route)

    # Kanalwechsel computation — Zusatzinfo, darf die Routenberechnung nie
    # scheitern lassen (z. B. bei unerwarteten Leitstellen-Geometrien).
    try:
        kanalwechsel = await _compute_kanalwechsel(db, line, route_data["distance_m"], convoy.organization_id)
    except Exception:
        logger.exception("Kanalwechsel computation failed for convoy %s", convoy_id)
        await db.rollback()
        kanalwechsel = []
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
        "planned_departure": route_planned_departure,
        "planned_arrival": route_planned_arrival,
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
         "license_plate": cv.vehicle.license_plate, "position": cv.position,
         "propulsion": getattr(cv.vehicle, "propulsion", "combustion")}
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
    # PDF generation (FPDF, font loading, many tables) is CPU-bound and
    # blocking — run it in the default thread pool so it does not stall the
    # event loop for concurrent requests.
    loop = asyncio.get_running_loop()
    pdf_bytes = await loop.run_in_executor(
        None, pdf_svc.generate_marschbefehl, convoy, waypoints, vehicles, route, kanalwechsel
    )
    filename = f"Marschbefehl_{_safe_filename(convoy.name.replace(' ', '_'))}.pdf"
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
    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
    try:
        result = importer_svc.parse_gpx(content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
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
    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
    try:
        result = importer_svc.parse_geojson(content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return await _apply_import(convoy_id, result, mode, db)


@router.get("/{convoy_id}/fuel-stations")
async def find_fuel_stations(
    convoy_id: uuid.UUID,
    lat: float,
    lon: float,
    radius_m: int = Query(3000, ge=100, le=50000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Find fuel stations near (lat, lon) – typically the recommended stop position."""
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise HTTPException(status_code=422, detail="Invalid coordinates")
    if not (100 <= radius_m <= 50_000):
        raise HTTPException(status_code=422, detail="radius_m must be between 100 and 50000")
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
