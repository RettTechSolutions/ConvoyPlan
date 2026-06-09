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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal, get_db
from app.models.convoy import Convoy, ConvoyVehicle
from app.services.rate_limit import rate_limit, register_failure
from app.models.route import Route
from app.models.share_link import ConvoyShareLink
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


async def _build_payload(convoy_id: uuid.UUID, db: AsyncSession) -> TrackPublic:
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
        waypoints=waypoints,
        geojson=geo_svc.linestring_to_geojson(route.geometry) if route else None,
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

    payload = await _build_payload(link.convoy_id, db)
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

    await tracking_manager.connect(convoy_id, ws)
    try:
        while True:
            # Read-only: drain any incoming frames (heartbeats etc.) and discard.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("track_ws error for slug %s: %s", slug, exc)
    finally:
        tracking_manager.disconnect(convoy_id, ws)
