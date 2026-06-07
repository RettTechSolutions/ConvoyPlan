import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from jose import jwt, JWTError
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.guards import get_convoy_access
from app.config import settings
from app.database import get_db, AsyncSessionLocal
from app.models.convoy import ConvoyVehicle
from app.models.user import User
from app.models.vehicle_position import VehiclePosition
from app.services.tracking import tracking_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tracking"])


class PositionUpdate(BaseModel):
    vehicle_id: uuid.UUID
    lat: float
    lon: float
    speed_kmh: float | None = None
    heading: float | None = None


class VehicleStatusUpdate(BaseModel):
    vehicle_status: Literal["planned", "en_route", "arrived", "delayed"]


@router.get("/convoys/{convoy_id}/positions")
async def get_positions(
    convoy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_convoy_access(convoy_id, current_user, db, require="read")
    result = await db.execute(
        select(VehiclePosition).where(VehiclePosition.convoy_id == convoy_id)
    )
    positions = result.scalars().all()
    return [
        {
            "vehicle_id": str(p.vehicle_id),
            "lat": p.lat,
            "lon": p.lon,
            "speed_kmh": p.speed_kmh,
            "heading": p.heading,
            "recorded_at": p.recorded_at.isoformat(),
        }
        for p in positions
    ]


@router.post("/convoys/{convoy_id}/positions")
async def update_position(
    convoy_id: uuid.UUID,
    data: PositionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_convoy_access(convoy_id, current_user, db, require="fahrer")
    # An admin just reset this vehicle's sharing — drop the late in-flight tick so
    # it can't re-create the position the admin removed.
    if tracking_manager.is_recently_cleared(str(convoy_id), str(data.vehicle_id)):
        return {"status": "suppressed"}
    stmt = (
        pg_insert(VehiclePosition)
        .values(
            convoy_id=convoy_id,
            vehicle_id=data.vehicle_id,
            lat=data.lat,
            lon=data.lon,
            speed_kmh=data.speed_kmh,
            heading=data.heading,
            recorded_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_update(
            index_elements=["convoy_id", "vehicle_id"],
            set_={
                "lat": data.lat,
                "lon": data.lon,
                "speed_kmh": data.speed_kmh,
                "heading": data.heading,
                "recorded_at": datetime.now(timezone.utc),
            },
        )
    )
    await db.execute(stmt)
    await db.commit()

    payload = {
        "vehicle_id": str(data.vehicle_id),
        "lat": data.lat,
        "lon": data.lon,
        "speed_kmh": data.speed_kmh,
        "heading": data.heading,
    }
    await tracking_manager.broadcast(str(convoy_id), payload)
    return {"status": "ok"}


@router.patch("/convoys/{convoy_id}/vehicles/{vehicle_id}/status")
async def update_vehicle_status(
    convoy_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    data: VehicleStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_convoy_access(convoy_id, current_user, db, require="fahrer")
    result = await db.execute(
        select(ConvoyVehicle).where(
            ConvoyVehicle.convoy_id == convoy_id,
            ConvoyVehicle.vehicle_id == vehicle_id,
        )
    )
    cv = result.scalar_one_or_none()
    if not cv:
        raise HTTPException(status_code=404, detail="Fahrzeug nicht im Verband")
    cv.vehicle_status = data.vehicle_status
    await db.commit()

    await tracking_manager.broadcast(str(convoy_id), {
        "type": "status_update",
        "vehicle_id": str(vehicle_id),
        "vehicle_status": data.vehicle_status,
    })
    return {"status": "ok"}


@router.delete("/convoys/{convoy_id}/vehicles/{vehicle_id}/position")
async def clear_vehicle_position(
    convoy_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    suppress: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """GPS-Freigabe eines Fahrzeugs beenden.

    Löscht die gespeicherte Position und sendet ein ``position_cleared``-Event,
    damit verbundene Clients den Marker entfernen.

    Wird sowohl vom Admin ("GPS-Freigaben" zurücksetzen) als auch vom Fahrer
    beim Stoppen des eigenen Sendens genutzt – daher Fahrer-Berechtigung.

    ``suppress``: kurzzeitig verspätete Positions-Ticks des Fahrzeugs verwerfen.
    Beim Admin-Reset ``True`` (der fremde Fahrer sendet evtl. noch), beim
    Selbst-Stopp ``False`` (der Fahrer hat bereits gestoppt und darf sofort
    wieder starten).
    """
    await get_convoy_access(convoy_id, current_user, db, require="fahrer")
    await db.execute(
        delete(VehiclePosition).where(
            VehiclePosition.convoy_id == convoy_id,
            VehiclePosition.vehicle_id == vehicle_id,
        )
    )
    await db.commit()

    if suppress:
        tracking_manager.mark_cleared(str(convoy_id), str(vehicle_id))
    await tracking_manager.broadcast(str(convoy_id), {
        "type": "position_cleared",
        "vehicle_id": str(vehicle_id),
    })
    return {"status": "ok"}


@router.websocket("/ws/tracking/{convoy_id}")
async def tracking_ws(
    convoy_id: str,
    ws: WebSocket,
    token: str = Query(...),
):
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
        if not user_id:
            await ws.close(code=4001)
            return
    except JWTError:
        await ws.close(code=4001)
        return

    async with AsyncSessionLocal() as db:
        try:
            convoy_uuid = uuid.UUID(convoy_id)
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if not user:
                await ws.close(code=4401)
                return
            await get_convoy_access(convoy_uuid, user, db, require="read")
        except HTTPException as exc:
            await ws.close(code=4403 if exc.status_code == 403 else 4404)
            return
        except ValueError:
            await ws.close(code=4400)
            return

    await tracking_manager.connect(convoy_id, ws)
    try:
        while True:
            data = await ws.receive_json()
            # Client kann Positionen über WS schicken
            # Verworfen, falls ein Admin die Freigabe gerade zurückgesetzt hat.
            if tracking_manager.is_recently_cleared(convoy_id, str(data.get("vehicle_id"))):
                continue
            async with AsyncSessionLocal() as db:
                try:
                    await get_convoy_access(uuid.UUID(convoy_id), user, db, require="fahrer")
                except HTTPException:
                    await ws.close(code=4403)
                    return
                stmt = (
                    pg_insert(VehiclePosition)
                    .values(
                        convoy_id=uuid.UUID(convoy_id),
                        vehicle_id=uuid.UUID(data["vehicle_id"]),
                        lat=data["lat"],
                        lon=data["lon"],
                        speed_kmh=data.get("speed_kmh"),
                        heading=data.get("heading"),
                        recorded_at=datetime.now(timezone.utc),
                    )
                    .on_conflict_do_update(
                        index_elements=["convoy_id", "vehicle_id"],
                        set_={
                            "lat": data["lat"],
                            "lon": data["lon"],
                            "speed_kmh": data.get("speed_kmh"),
                            "heading": data.get("heading"),
                            "recorded_at": datetime.now(timezone.utc),
                        },
                    )
                )
                await db.execute(stmt)
                await db.commit()

            await tracking_manager.broadcast(convoy_id, {**data, "type": "position"})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WebSocket error for convoy %s: %s", convoy_id, exc)
        raise
    finally:
        tracking_manager.disconnect(convoy_id, ws)

