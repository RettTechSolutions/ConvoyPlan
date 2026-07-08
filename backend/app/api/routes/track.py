"""Public live-tracking share link endpoints.

These endpoints are reachable without login — access is gated by the slug and
(optionally) a password. They MUST stay under /api/track/* and /api/ws/track/*
so the license-guard whitelist matches.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal, get_db
from app.models.convoy import Convoy, ConvoyVehicle
from app.services.rate_limit import rate_limit, register_failure
from app.models.route import Route
from app.models.share_link import ConvoyShareLink
from app.models.vehicle import Vehicle
from app.models.vehicle_position import VehiclePosition
from app.schemas.share_link import (
    TrackAuthRequest,
    TrackAuthResponse,
    TrackGate,
    TrackPosition,
    TrackPublic,
    TrackVehicle,
    TrackWaypoint,
)
from app.services import geometry as geo_svc
from app.services import share_links as share_links_svc
from app.services import vehicle_status as vs
from app.services.tracking import tracking_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/track", tags=["track"])
ws_router = APIRouter(prefix="/ws/track", tags=["track"])


async def _load_link(slug: str, db: AsyncSession) -> ConvoyShareLink:
    result = await db.execute(
        select(ConvoyShareLink).where(ConvoyShareLink.slug == slug)
    )
    link = result.scalar_one_or_none()
    if not link or link.revoked:
        raise HTTPException(status_code=404, detail="Tracking-Link nicht gefunden")
    return link


async def _bump_access(db: AsyncSession, link_id: uuid.UUID) -> None:
    await db.execute(
        update(ConvoyShareLink)
        .where(ConvoyShareLink.id == link_id)
        .values(
            access_count=ConvoyShareLink.access_count + 1,
            last_accessed_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()


async def _build_payload(convoy_id: uuid.UUID, db: AsyncSession, scope: str = "track") -> TrackPublic:
    convoy_result = await db.execute(
        select(Convoy)
        .where(Convoy.id == convoy_id)
        .options(
            selectinload(Convoy.waypoints),
            selectinload(Convoy.convoy_vehicles).selectinload(ConvoyVehicle.vehicle),
        )
    )
    convoy = convoy_result.scalar_one_or_none()
    if not convoy:
        raise HTTPException(status_code=404, detail="Marschverband nicht gefunden")

    route_result = await db.execute(select(Route).where(Route.convoy_id == convoy_id))
    route = route_result.scalar_one_or_none()

    pos_result = await db.execute(
        select(VehiclePosition).where(VehiclePosition.convoy_id == convoy_id)
    )
    positions = pos_result.scalars().all()

    waypoints_sorted = sorted(convoy.waypoints, key=lambda w: w.order_index)
    waypoints = [
        TrackWaypoint(
            name=w.name,
            type=w.type,
            **geo_svc.waypoint_coords(w),
            planned_arrival=w.planned_arrival,
            planned_departure=w.planned_departure,
            halt_purpose=getattr(w, "halt_purpose", None),
        )
        for w in waypoints_sorted
    ]
    vehicles = [
        TrackVehicle(
            id=cv.vehicle_id,
            name=cv.vehicle.name,
            callsign=cv.vehicle.callsign,
            sonderfunktion=cv.sonderfunktion,
            vehicle_status=cv.vehicle_status,
            position=cv.position,
        )
        for cv in sorted(convoy.convoy_vehicles, key=lambda c: c.position)
    ]
    track_positions = [
        TrackPosition(
            vehicle_id=p.vehicle_id,
            lat=p.lat,
            lon=p.lon,
            speed_kmh=p.speed_kmh,
            heading=p.heading,
            recorded_at=p.recorded_at,
        )
        for p in positions
    ]

    return TrackPublic(
        name=convoy.name,
        organization=convoy.organization,
        start_time=convoy.start_time,
        scope=scope,
        waypoints=waypoints,
        geojson=geo_svc.linestring_to_geojson(route.geometry) if route else None,
        distance_m=route.distance_m if route else None,
        kanalwechsel=(route.kanalwechsel or []) if route else [],
        vehicles=vehicles,
        positions=track_positions,
    )


@router.get("/{slug}", response_model=TrackPublic | TrackGate)
async def get_track(
    slug: str,
    db: AsyncSession = Depends(get_db),
    x_track_token: str | None = Header(default=None, alias="X-Track-Token"),
):
    link = await _load_link(slug, db)

    if link.password_hash is not None:
        token_slug = share_links_svc.decode_session_token(x_track_token) if x_track_token else None
        if token_slug != slug:
            convoy_result = await db.execute(
                select(Convoy.name).where(Convoy.id == link.convoy_id)
            )
            convoy_name = convoy_result.scalar_one_or_none() or ""
            return TrackGate(requires_password=True, convoy_name=convoy_name)

    payload = await _build_payload(link.convoy_id, db, scope=link.scope)
    await _bump_access(db, link.id)
    return payload


@router.post(
    "/{slug}/auth",
    response_model=TrackAuthResponse,
    dependencies=[Depends(rate_limit("track-auth", max_attempts=5, window_seconds=300))],
)
async def auth_track(
    slug: str,
    data: TrackAuthRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    link = await _load_link(slug, db)
    if link.password_hash is None:
        raise HTTPException(status_code=400, detail="Dieser Link ist nicht passwortgeschützt")
    if not share_links_svc.verify_password(data.password, link.password_hash):
        register_failure(request, "track-auth")
        await asyncio.sleep(0.5)  # mild brute-force friction
        raise HTTPException(status_code=401, detail="Falsches Passwort")
    return TrackAuthResponse(token=share_links_svc.issue_session_token(slug))


async def _ingest_driver_position(convoy_uuid: uuid.UUID, msg: dict) -> None:
    """Persist + broadcast a position sent by a "driver" share-link holder.

    Authorization happens at connect time (slug + scope + optional password);
    the vehicle must belong to the convoy. On the first movement a vehicle that
    is still "planned" is auto-advanced to "en_route", mirroring the authed app.
    """
    try:
        vehicle_id = uuid.UUID(str(msg.get("vehicle_id")))
        lat = float(msg["lat"])
        lon = float(msg["lon"])
    except (KeyError, TypeError, ValueError):
        return
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return
    speed = msg.get("speed_kmh")
    heading = msg.get("heading")
    speed = float(speed) if isinstance(speed, (int, float)) else None
    heading = float(heading) if isinstance(heading, (int, float)) else None
    if heading is not None and not (0 <= heading < 360):
        heading = None

    async with AsyncSessionLocal() as db:
        cv = await db.get(ConvoyVehicle, (convoy_uuid, vehicle_id))
        if cv is None:
            return  # vehicle is not part of this convoy → ignore
        stmt = (
            pg_insert(VehiclePosition)
            .values(
                convoy_id=convoy_uuid, vehicle_id=vehicle_id, lat=lat, lon=lon,
                speed_kmh=speed, heading=heading, recorded_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                index_elements=["convoy_id", "vehicle_id"],
                set_={"lat": lat, "lon": lon, "speed_kmh": speed, "heading": heading,
                      "recorded_at": datetime.now(timezone.utc)},
            )
        )
        await db.execute(stmt)
        auto_status = None
        if cv.vehicle_status == "planned":
            cv.vehicle_status = "en_route"
            cv.status_changed_at = datetime.now(timezone.utc)
            auto_status = "en_route"
        await db.commit()

    await tracking_manager.broadcast(str(convoy_uuid), {
        "type": "position", "vehicle_id": str(vehicle_id),
        "lat": lat, "lon": lon, "speed_kmh": speed, "heading": heading,
    })
    if auto_status:
        await tracking_manager.broadcast(str(convoy_uuid), {
            "type": "status_update", "vehicle_id": str(vehicle_id),
            "vehicle_status": auto_status, "status_level": None, "status_note": None,
        })


async def _ingest_driver_status(convoy_uuid: uuid.UUID, msg: dict) -> None:
    """Persist + broadcast a status change sent by a "driver" share-link holder."""
    try:
        vehicle_id = uuid.UUID(str(msg.get("vehicle_id")))
        status = str(msg["vehicle_status"])
    except (KeyError, TypeError, ValueError):
        return
    if status not in vs.VALID_VEHICLE_STATUSES:
        return
    try:
        level = vs.normalize_level(status, msg.get("status_level"))
    except ValueError:
        return
    note = msg.get("status_note")
    note = str(note)[:200] if isinstance(note, str) and note.strip() else None

    async with AsyncSessionLocal() as db:
        cv = await db.get(ConvoyVehicle, (convoy_uuid, vehicle_id))
        if cv is None:
            return
        cv.vehicle_status = status
        cv.status_level = level
        cv.status_note = note
        cv.status_changed_at = datetime.now(timezone.utc)
        await db.commit()
        ts = cv.status_changed_at.isoformat()
        vehicle = await db.get(Vehicle, vehicle_id)
        vehicle_label = (vehicle.callsign or vehicle.name) if vehicle else None

    await tracking_manager.broadcast(str(convoy_uuid), {
        "type": "status_update", "vehicle_id": str(vehicle_id),
        "vehicle_status": status, "status_level": level, "status_note": note,
    })
    if status in vs.ALERT_STATUSES:
        await tracking_manager.broadcast(str(convoy_uuid), {
            "type": "alert", "alert_type": status, "vehicle_id": str(vehicle_id),
            "vehicle_label": vehicle_label, "level": level, "note": note, "ts": ts,
        })


@ws_router.websocket("/{slug}")
async def track_ws(slug: str, ws: WebSocket, token: str | None = Query(default=None)):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ConvoyShareLink).where(ConvoyShareLink.slug == slug)
        )
        link = result.scalar_one_or_none()
        if not link or link.revoked:
            await ws.close(code=4404)
            return
        if link.password_hash is not None:
            token_slug = share_links_svc.decode_session_token(token) if token else None
            if token_slug != slug:
                await ws.close(code=4001)
                return
        convoy_id = str(link.convoy_id)
        convoy_uuid = link.convoy_id
        is_driver = link.scope == "driver"

    await tracking_manager.connect(convoy_id, ws)
    try:
        while True:
            raw = await ws.receive_json()
            # Viewer links are read-only — drained frames (heartbeats) are ignored.
            if not is_driver or not isinstance(raw, dict):
                continue
            if raw.get("type") == "status":
                await _ingest_driver_status(convoy_uuid, raw)
            else:
                await _ingest_driver_position(convoy_uuid, raw)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("track_ws error for slug %s: %s", slug, exc)
    finally:
        tracking_manager.disconnect(convoy_id, ws)
