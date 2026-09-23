import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import decode_stream_token, get_current_user
from app.api.guards import get_convoy_access
from app.database import get_db, AsyncSessionLocal
from app.models.convoy import ConvoyVehicle
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_position import VehiclePosition
from app.services import alarm_quittung
from app.services import betriebsstoff as betriebsstoff_svc
from app.services import belegung
from app.services import staerke as staerke_svc
from app.services import vehicle_status as vs
from app.services.tracking import tracking_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tracking"])


class PositionUpdate(BaseModel):
    vehicle_id: uuid.UUID
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    speed_kmh: float | None = Field(None, ge=0)
    heading: float | None = Field(None, ge=0, lt=360)

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError("Latitude must be between -90 and 90")
        return v

    @field_validator("lon")
    @classmethod
    def validate_lon(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError("Longitude must be between -180 and 180")
        return v


_VALID_VEHICLE_STATUSES = {"planned", "en_route", "arrived", "technical_halt", "breakdown"}
# Allowed sub-levels per status. Statuses not listed must not carry a level.
_VALID_STATUS_LEVELS = {
    "technical_halt": {"standard", "dringend", "sehr_dringend"},
    "breakdown": {"total", "limited"},
}
# Statuses that trigger an in-app alert to the convoy leadership / all clients.
_ALERT_STATUSES = {"technical_halt", "breakdown"}


class VehicleStatusUpdate(BaseModel):
    vehicle_status: str
    status_level: str | None = None
    status_note: str | None = Field(None, max_length=200)

    @field_validator("vehicle_status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        if v not in vs.VALID_VEHICLE_STATUSES:
            raise ValueError(f"vehicle_status must be one of {sorted(vs.VALID_VEHICLE_STATUSES)}")
        return v

    @model_validator(mode="after")
    def _check_level(self) -> "VehicleStatusUpdate":
        allowed = _VALID_STATUS_LEVELS.get(self.vehicle_status)
        if allowed is None:
            # Status without sub-levels — drop any stray level.
            self.status_level = None
        elif self.status_level is not None and self.status_level not in allowed:
            raise ValueError(f"status_level for {self.vehicle_status} must be one of {sorted(allowed)}")
        return self


class StaerkeUpdate(BaseModel):
    """Eine gemeldete Mannschaftsstärke.

    Die Gesamtzahl kommt nicht von außen — sie wird gerechnet. Die Grenzen
    stehen in ``services/staerke.py``, damit der Fahrer-Link dieselben prüft.
    """

    fuehrer: int = Field(0, ge=0, le=staerke_svc.MAX_JE_ROLLE)
    unterfuehrer: int = Field(0, ge=0, le=staerke_svc.MAX_JE_ROLLE)
    mannschaften: int = Field(0, ge=0, le=staerke_svc.MAX_JE_ROLLE)


class BetriebsstoffUpdate(BaseModel):
    """Eine nachgetragene Betriebsstofflage.

    Dieselben Regeln wie über den Fahrer-Link (``services/betriebsstoff.py``):
    fehlende Angaben bleiben ``None`` und heißen „nicht bekannt", eine
    unplausible Angabe weist die ganze Meldung ab. Anders als dort gibt es hier
    eine Antwort — also ein 422 statt stillem Verwerfen.
    """

    verbrauch: float | None = None
    tank: int | None = None
    fuellstand: int | None = None

    @model_validator(mode="after")
    def pruefen(self):
        werte = betriebsstoff_svc.normalisieren(self.verbrauch, self.tank, self.fuellstand)
        if werte is None:
            raise ValueError("Ohne Angabe ist das keine Meldung")
        self.verbrauch, self.tank, self.fuellstand = werte
        return self


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
    cv.status_level = data.status_level
    cv.status_note = data.status_note
    cv.status_changed_at = datetime.now(timezone.utc)
    alarm_quittung.zuruecksetzen(cv)
    await db.commit()

    await tracking_manager.broadcast(str(convoy_id), {
        "type": "status_update",
        "vehicle_id": str(vehicle_id),
        "vehicle_status": data.vehicle_status,
        "status_level": data.status_level,
        "status_note": data.status_note,
    })

    # Technische Halte und Ausfälle lösen einen In-App-Alarm aus, damit die
    # Konvoiführung (und bei Ausfall alle) sofort informiert sind.
    if data.vehicle_status in _ALERT_STATUSES:
        # Klartext-Bezeichnung des anfordernden Fahrzeugs für die Meldung.
        vehicle = await db.get(Vehicle, vehicle_id)
        vehicle_label = None
        if vehicle:
            vehicle_label = vehicle.callsign or vehicle.name
        await tracking_manager.broadcast(str(convoy_id), {
            "type": "alert",
            "alert_type": data.vehicle_status,
            "vehicle_id": str(vehicle_id),
            "vehicle_label": vehicle_label,
            "level": data.status_level,
            "note": data.status_note,
            "ts": cv.status_changed_at.isoformat(),
        })
    return {"status": "ok"}


@router.patch("/convoys/{convoy_id}/vehicles/{vehicle_id}/staerke")
async def update_vehicle_staerke(
    convoy_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    data: StaerkeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mannschaftsstärke eines Fahrzeugs setzen.

    Denselben Weg nimmt die Besatzung über den Fahrer-Link; hier kommt er für
    die Führung dazu, die eine per Funk durchgegebene Stärke nachträgt.
    """
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

    cv.staerke_ist_fuehrer = data.fuehrer
    cv.staerke_ist_unterfuehrer = data.unterfuehrer
    cv.staerke_ist_mannschaften = data.mannschaften
    cv.staerke_gemeldet_at = datetime.now(timezone.utc)
    await db.commit()

    gesamt = staerke_svc.gesamt(data.fuehrer, data.unterfuehrer, data.mannschaften)
    await tracking_manager.broadcast(str(convoy_id), {
        "type": "staerke_update",
        "vehicle_id": str(vehicle_id),
        "fuehrer": data.fuehrer,
        "unterfuehrer": data.unterfuehrer,
        "mannschaften": data.mannschaften,
        "gesamt": gesamt,
    })
    return {"status": "ok", "gesamt": gesamt}


@router.patch("/convoys/{convoy_id}/vehicles/{vehicle_id}/betriebsstoff")
async def update_vehicle_betriebsstoff(
    convoy_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    data: BetriebsstoffUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Betriebsstofflage eines Fahrzeugs setzen.

    Die Besatzung meldet über den Fahrer-Link; hier trägt die Führung nach, was
    per Funk durchgegeben wurde. Dieselbe Schwelle wie bei der Stärke: wer
    meldet, muss mindestens ``fahrer`` sein. Die Meldung ersetzt die vorige
    ganz, wie auf dem anderen Weg auch.
    """
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

    werte = (data.verbrauch, data.tank, data.fuellstand)
    cv.betriebsstoff_verbrauch, cv.betriebsstoff_tank, cv.betriebsstoff_fuellstand = werte
    cv.betriebsstoff_gemeldet_at = datetime.now(timezone.utc)
    await db.commit()

    nachricht = betriebsstoff_svc.update_nachricht(vehicle_id, werte, cv.betriebsstoff_gemeldet_at)
    await tracking_manager.broadcast(str(convoy_id), nachricht)
    return {"status": "ok", "gemeldet_at": nachricht["gemeldet_at"]}


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
        # Die Führung setzt zurück: das Fahrzeug wird sofort frei, wer immer es
        # hält. Beim Selbst-Stopp bleibt die Belegung — das Fahrzeug ist ja
        # weiter gewählt; frei wird es mit dem Abwählen (``freigeben``).
        await belegung.freigeben(str(convoy_id), str(vehicle_id), None)
    await tracking_manager.broadcast(str(convoy_id), {
        "type": "position_cleared",
        "vehicle_id": str(vehicle_id),
    })
    return {"status": "ok"}


async def _belegung_bearbeiten(
    convoy_id: str, user: User, ws: WebSocket, raw: dict, kennung: str, durchsetzen: bool
) -> None:
    """``belegen``/``freigeben`` am angemeldeten Kanal — mit Fahrer-Recht."""
    try:
        vehicle_id = uuid.UUID(str(raw.get("vehicle_id")))
    except (TypeError, ValueError):
        return
    if raw.get("type") == "freigeben":
        await belegung.freigeben(convoy_id, str(vehicle_id), kennung)
        return
    async with AsyncSessionLocal() as db:
        try:
            await get_convoy_access(uuid.UUID(convoy_id), user, db, require="fahrer")
        except HTTPException:
            return
        if await db.get(ConvoyVehicle, (uuid.UUID(convoy_id), vehicle_id)) is None:
            return
    await belegung.pruefen(convoy_id, str(vehicle_id), kennung, ws, durchsetzen)


async def _alarm_quittieren(
    convoy_id: str, user: User, ws: WebSocket, raw: dict, kennung: str
) -> None:
    """Quittung am angemeldeten Kanal — mit Fahrer-Recht, wie jede Meldung.

    Wer quittiert hat, ist hier der Nutzer: sein Name, sonst seine Adresse.
    Die Antwort geht als ``ack`` an den Absender, sofern er eine ``client_id``
    mitschickt; ``alarm_quittiert`` an alle kommt aus dem Service.
    """
    client_id = raw.get("client_id")
    client_id = client_id if isinstance(client_id, str) and 0 < len(client_id) <= 64 else None
    async with AsyncSessionLocal() as db:
        try:
            await get_convoy_access(uuid.UUID(convoy_id), user, db, require="fahrer")
        except HTTPException:
            ergebnis = {"result": "rejected", "reason": "read-only"}
        else:
            ergebnis = None
    if ergebnis is None:
        name = " ".join(t for t in (user.first_name, user.last_name) if t) or user.email
        # Wie am Fahrer-Link: Den Alarm des Fahrzeugs, das dieses Gerät selbst
        # belegt, quittiert es nicht.
        eigene = belegung.belegungen.gehalten(convoy_id, kennung)
        ergebnis = await alarm_quittung.quittieren(uuid.UUID(convoy_id), raw, name, eigene)
    if client_id is not None:
        await ws.send_json(
            {"type": "ack", "client_id": client_id, "frame": "alarm_quittieren", **ergebnis}
        )


@router.websocket("/ws/tracking/{convoy_id}")
async def tracking_ws(
    convoy_id: str,
    ws: WebSocket,
    token: str = Query(...),
    client: str | None = Query(default=None),
):
    try:
        token_data = decode_stream_token(token)
    except HTTPException:
        await ws.close(code=4001)
        return

    async with AsyncSessionLocal() as db:
        try:
            convoy_uuid = uuid.UUID(convoy_id)
            user_result = await db.execute(select(User).where(User.id == token_data.user_id))
            user = user_result.scalar_one_or_none()
            if not user or not user.is_active:
                await ws.close(code=4401)
                return
            # Reject stale sessions (token_version bumped by password change/reset).
            if token_data.token_version != user.token_version:
                await ws.close(code=4401)
                return
            await get_convoy_access(convoy_uuid, user, db, require="read")
        except HTTPException as exc:
            await ws.close(code=4403 if exc.status_code == 403 else 4404)
            return
        except ValueError:
            await ws.close(code=4400)
            return

    # Belegung wie am Fahrer-Link (services/belegung.py): ohne Kennung ein
    # älterer Client, der nicht abgewiesen wird, aber belegt, was er sendet.
    kennung = belegung.kennung_pruefen(client)
    durchsetzen = kennung is not None
    kennung = kennung or belegung.alt_kennung()

    await tracking_manager.connect(convoy_id, ws, mit_kennung=durchsetzen)
    if durchsetzen:
        await belegung.stand_senden(convoy_id, kennung, ws)
    try:
        while True:
            raw = await ws.receive_json()
            # Application-level heartbeat: the client pings every few seconds so
            # it can detect a silently dropped (half-open) mobile connection
            # quickly. Reply with a pong and skip position handling.
            if isinstance(raw, dict) and raw.get("type") == "ping":
                await ws.send_json({"type": "pong"})
                continue
            if isinstance(raw, dict) and raw.get("type") == "alarm_quittieren":
                await _alarm_quittieren(convoy_id, user, ws, raw, kennung)
                continue
            if isinstance(raw, dict) and raw.get("type") in ("belegen", "freigeben"):
                await _belegung_bearbeiten(convoy_id, user, ws, raw, kennung, durchsetzen)
                continue
            try:
                pos = PositionUpdate.model_validate(raw)
            except Exception:
                continue
            # Verworfen, falls ein Admin die Freigabe gerade zurückgesetzt hat.
            if tracking_manager.is_recently_cleared(convoy_id, str(pos.vehicle_id)):
                continue
            async with AsyncSessionLocal() as db:
                try:
                    await get_convoy_access(uuid.UUID(convoy_id), user, db, require="fahrer")
                except HTTPException:
                    await ws.close(code=4403)
                    return
                cv = await db.get(ConvoyVehicle, (uuid.UUID(convoy_id), pos.vehicle_id))
                if cv is None:
                    continue
                if not await belegung.pruefen(
                    convoy_id, str(pos.vehicle_id), kennung, ws, durchsetzen
                ):
                    continue
                stmt = (
                    pg_insert(VehiclePosition)
                    .values(
                        convoy_id=uuid.UUID(convoy_id),
                        vehicle_id=pos.vehicle_id,
                        lat=pos.lat,
                        lon=pos.lon,
                        speed_kmh=pos.speed_kmh,
                        heading=pos.heading,
                        recorded_at=datetime.now(timezone.utc),
                    )
                    .on_conflict_do_update(
                        index_elements=["convoy_id", "vehicle_id"],
                        set_={
                            "lat": pos.lat,
                            "lon": pos.lon,
                            "speed_kmh": pos.speed_kmh,
                            "heading": pos.heading,
                            "recorded_at": datetime.now(timezone.utc),
                        },
                    )
                )
                await db.execute(stmt)
                await db.commit()

            await tracking_manager.broadcast(convoy_id, {
                "type": "position",
                "vehicle_id": str(pos.vehicle_id),
                "lat": pos.lat,
                "lon": pos.lon,
                "speed_kmh": pos.speed_kmh,
                "heading": pos.heading,
            })
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WebSocket error for convoy %s: %s", convoy_id, exc)
        raise
    finally:
        tracking_manager.disconnect(convoy_id, ws)

