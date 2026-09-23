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
from app.services import belegung
from app.services import geometry as geo_svc
from app.services import share_links as share_links_svc
from app.services import staerke as staerke_svc
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
            staerke_soll_fuehrer=cv.staerke_soll_fuehrer,
            staerke_soll_unterfuehrer=cv.staerke_soll_unterfuehrer,
            staerke_soll_mannschaften=cv.staerke_soll_mannschaften,
            staerke_ist_fuehrer=cv.staerke_ist_fuehrer,
            staerke_ist_unterfuehrer=cv.staerke_ist_unterfuehrer,
            staerke_ist_mannschaften=cv.staerke_ist_mannschaften,
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
            return TrackGate(
                requires_password=True,
                convoy_name=convoy_name,
                scope=link.scope,
            )

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


def _rejected(reason: str) -> dict:
    return {"result": "rejected", "reason": reason}


async def _ingest_driver_status(convoy_uuid: uuid.UUID, msg: dict) -> dict:
    """Persist + broadcast a status change sent by a "driver" share-link holder.

    Gibt das Ergebnis für die Quittung zurück (``_ack``). Wer keine
    ``client_id`` mitschickt, bekommt davon nichts zu sehen — für ihn bleibt
    der Kanal einseitig wie bisher.
    """
    try:
        vehicle_id = uuid.UUID(str(msg.get("vehicle_id")))
    except (TypeError, ValueError):
        return _rejected("invalid-vehicle")
    status = msg.get("vehicle_status")
    if not isinstance(status, str) or status not in vs.VALID_VEHICLE_STATUSES:
        return _rejected("unknown-status")
    try:
        level = vs.normalize_level(status, msg.get("status_level"))
    except ValueError:
        return _rejected("invalid-level")
    note = msg.get("status_note")
    note = str(note)[:200] if isinstance(note, str) and note.strip() else None

    async with AsyncSessionLocal() as db:
        cv = await db.get(ConvoyVehicle, (convoy_uuid, vehicle_id))
        if cv is None:
            return _rejected("vehicle-not-in-convoy")
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
    return {
        "result": "ok",
        "applied": {"vehicle_status": status, "status_level": level, "status_note": note},
        "ts": ts,
    }


async def _ingest_driver_staerke(convoy_uuid: uuid.UUID, msg: dict) -> dict:
    """Persist + broadcast a crew strength sent by a "driver" share-link holder.

    Wie beim Status: die Berechtigung entstand beim Verbinden, das Fahrzeug muss
    zu diesem Verband gehören. Eine unplausible Meldung wird verworfen statt
    beantwortet — der Kanal ist einseitig, und die alte Zahl ist allemal besser
    als eine falsche.
    """
    try:
        vehicle_id = uuid.UUID(str(msg.get("vehicle_id")))
    except (TypeError, ValueError):
        return _rejected("invalid-vehicle")
    try:
        werte = staerke_svc.normalisieren(
            msg.get("fuehrer"), msg.get("unterfuehrer"), msg.get("mannschaften")
        )
    except (TypeError, ValueError):
        return _rejected("invalid-staerke")
    if werte is None:
        return _rejected("invalid-staerke")  # eine Meldung ohne jede Zahl ist keine
    fuehrer, unterfuehrer, mannschaften = werte

    async with AsyncSessionLocal() as db:
        cv = await db.get(ConvoyVehicle, (convoy_uuid, vehicle_id))
        if cv is None:
            return _rejected("vehicle-not-in-convoy")
        cv.staerke_ist_fuehrer = fuehrer
        cv.staerke_ist_unterfuehrer = unterfuehrer
        cv.staerke_ist_mannschaften = mannschaften
        cv.staerke_gemeldet_at = datetime.now(timezone.utc)
        await db.commit()
        ts = cv.staerke_gemeldet_at.isoformat()

    await tracking_manager.broadcast(str(convoy_uuid), {
        "type": "staerke_update", "vehicle_id": str(vehicle_id),
        "fuehrer": fuehrer, "unterfuehrer": unterfuehrer, "mannschaften": mannschaften,
        "gesamt": fuehrer + unterfuehrer + mannschaften,
    })
    return {
        "result": "ok",
        "applied": {"fuehrer": fuehrer, "unterfuehrer": unterfuehrer, "mannschaften": mannschaften},
        "ts": ts,
    }


# ── Quittung ──────────────────────────────────────────────────────────────────
#
# Der Fahrer muss wissen, ob seine Meldung angekommen ist. Das Echo im Broadcast
# sagt es nur ungefähr: Es trägt keinen Absender, bleibt bei einer Ablehnung
# stumm, und ein Frame, der im Funkloch zwischen Socket und Server verloren ging,
# sieht aus wie einer, auf den der Server nur noch nicht geantwortet hat.
#
# Deshalb antwortet der Server auf Status- und Stärke-Frames mit einer
# ``client_id`` ausdrücklich — und nur dem Absender. Ohne ``client_id`` bleibt
# alles wie gehabt; die PWA und ältere Apps merken nichts davon.

# Was der Server auf dieser Verbindung kann. Kommt beim Verbinden als erster
# Frame, damit ein Client weiß, ob er auf eine Quittung warten darf — ein
# älterer Server schickt keinen, und dann bleibt nur das Echo.
HELLO = {"type": "hello", "protocol": 2, "features": ["ack"]}

_CLIENT_ID_MAX = 64


def _client_id(raw: dict) -> str | None:
    """Die Kennung des Frames, wenn er eine brauchbare trägt."""
    value = raw.get("client_id")
    if isinstance(value, str) and 0 < len(value) <= _CLIENT_ID_MAX:
        return value
    return None


def _ack(client_id: str, frame: str, result: dict) -> dict:
    return {"type": "ack", "client_id": client_id, "frame": frame, **result}


async def _ingest_acked(convoy_uuid: uuid.UUID, frame: str, raw: dict, client_id: str) -> dict:
    """Verarbeitet einen Frame **höchstens einmal** und liefert seine Quittung.

    Schickt der Client denselben Frame erneut — weil die Verbindung abriss, ehe
    die Quittung ankam —, bekommt er die Quittung des ersten Durchlaufs. Die
    Meldung selbst wird nicht wiederholt: Ein zweiter technischer Halt wäre ein
    zweiter Alarm bei allen Beteiligten.
    """
    key = (str(convoy_uuid), client_id)
    known = tracking_manager.claim_ack(key)
    if known is not None:
        return await known

    ingest = _ingest_driver_status if frame == "status" else _ingest_driver_staerke
    try:
        result = _ack(client_id, frame, await ingest(convoy_uuid, raw))
    except Exception:
        # Nicht merken: Ein Fehler hier ist keine Antwort auf den Frame, und
        # ein erneuter Versuch darf es noch einmal probieren.
        logger.warning("track_ws: %s-Frame nicht verarbeitet", frame, exc_info=True)
        failed = _ack(client_id, frame, _rejected("server-error"))
        tracking_manager.forget_ack(key, failed)
        return failed
    except BaseException:
        # Abgebrochen (Herunterfahren, Verbindungsende): Ohne Freigabe warteten
        # Duplikate auf ein Ergebnis, das nie kommt.
        tracking_manager.forget_ack(key, _ack(client_id, frame, _rejected("server-error")))
        raise
    tracking_manager.settle_ack(key, result)
    return result


def _fahrzeug_aus(raw: dict) -> str | None:
    try:
        return str(uuid.UUID(str(raw.get("vehicle_id"))))
    except (TypeError, ValueError):
        return None


async def _im_verband(convoy_uuid: uuid.UUID, vehicle_id: str) -> bool:
    async with AsyncSessionLocal() as db:
        return await db.get(ConvoyVehicle, (convoy_uuid, uuid.UUID(vehicle_id))) is not None


@ws_router.websocket("/{slug}")
async def track_ws(
    slug: str,
    ws: WebSocket,
    token: str | None = Query(default=None),
    client: str | None = Query(default=None),
):
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

    # Ohne Kennung: ein Client von vor der Belegung. Er sendet weiter wie bisher,
    # belegt aber, was er sendet (services/belegung.py).
    kennung = belegung.kennung_pruefen(client)
    durchsetzen = kennung is not None
    kennung = kennung or belegung.alt_kennung()
    # Fahrzeuge, die schon als Teil des Verbands bestätigt sind — erspart die
    # Abfrage bei jeder Position.
    bekannt: set[str] = set()

    await tracking_manager.connect(convoy_id, ws, mit_kennung=durchsetzen)
    if durchsetzen:
        await belegung.stand_senden(convoy_id, kennung, ws)
    if durchsetzen:
        # Neue Nachrichtentypen nur an Verbindungen mit Gerätekennung — wie die
        # Belegung (``tracking_manager.connect``): Wer keine mitbringt, ist älter
        # als beides und kennt den Typ nicht.
        await ws.send_json(HELLO)
    try:
        while True:
            raw = await ws.receive_json()
            if not isinstance(raw, dict):
                continue
            kind = raw.get("type")
            client_id = _client_id(raw) if kind in ("status", "staerke") else None
            # Viewer links are read-only — drained frames (heartbeats) are ignored.
            # Wer ausdrücklich nach einer Quittung fragt, erfährt, warum nichts geschah.
            if not is_driver:
                if client_id is not None:
                    await ws.send_json(_ack(client_id, kind, _rejected("read-only")))
                continue
            vehicle_id = _fahrzeug_aus(raw)
            if vehicle_id is None:
                if client_id is not None:
                    await ws.send_json(_ack(client_id, kind, _rejected("invalid-vehicle")))
                continue
            if kind == "freigeben":
                await belegung.freigeben(convoy_id, vehicle_id, kennung)
                continue
            if vehicle_id not in bekannt:
                if not await _im_verband(convoy_uuid, vehicle_id):
                    # nicht in diesem Verband → nichts zu belegen
                    if client_id is not None:
                        await ws.send_json(
                            _ack(client_id, kind, _rejected("vehicle-not-in-convoy"))
                        )
                    continue
                bekannt.add(vehicle_id)
            if not await belegung.pruefen(convoy_id, vehicle_id, kennung, ws, durchsetzen):
                # `belegung_abgelehnt` ist schon beim Absender. Die Quittung sagt
                # dasselbe noch einmal für die Meldung, die er gerade abgab.
                if client_id is not None:
                    await ws.send_json(_ack(client_id, kind, _rejected("vehicle-taken")))
                continue
            if kind == "belegen":
                continue
            if client_id is not None:
                await ws.send_json(await _ingest_acked(convoy_uuid, kind, raw, client_id))
            elif kind == "status":
                await _ingest_driver_status(convoy_uuid, raw)
            elif kind == "staerke":
                await _ingest_driver_staerke(convoy_uuid, raw)
            else:
                await _ingest_driver_position(convoy_uuid, raw)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("track_ws error for slug %s: %s", slug, exc)
    finally:
        tracking_manager.disconnect(convoy_id, ws)
