"""Ortungsgeräte: Geräte-API für den Tracker und Verwaltung im Org-Admin.

Zwei Router in einer Datei, wie bei der Aktionsseite: was die Organisation
einstellt und was das Gerät damit darf, gehört zusammen gelesen. Die Regeln
— wann gesendet wird, welche Fixes gelten, wer die aktuelle Position gewinnt —
stehen in ``services/ortungsgeraet.py``; hier ist nur die Verdrahtung.

Das Gerät weist sich mit ``Authorization: Bearer cvt_…`` aus. Unbekanntes,
widerrufenes oder gesperrtes Token: 401, und das Gerät fällt in den Zustand
*gesperrt* (nur noch Lebenszeichen). Der Einmal-Code aus dem Org-Admin wird
beim Einlösen gegen das Token getauscht; unbekannt, abgelaufen oder schon
eingelöst ergeben dieselbe 404.

Dies ist die **vierte** Stelle, die ``VehiclePosition`` schreibt — neben
Fahrer-Link, REST und WebSocket der angemeldeten Ansicht. Deshalb ruft sie wie
die drei anderen ``positionsverlauf.aufzeichnen`` auf, achtet auf
``is_recently_cleared`` („GPS-Freigabe zurücksetzen" gilt auch für einen
Tracker) und hebt ein geplantes Fahrzeug beim ersten Fix auf ``en_route``.
"""
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import OrgCtx, get_org_context
from app.api.guards import ROLE_ORDER
from app.database import get_db
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.ortungsgeraet import Ortungsgeraet
from app.models.vehicle import Vehicle
from app.models.vehicle_position import VehiclePosition
from app.services import alarm_quittung, audit, firmware_angebot, org_plan, positionsquelle, positionsverlauf
from app.services import tracker_wurzeln as tw
from app.services import ortungsgeraet as og
from app.services.rate_limit import rate_limit
from app.services.tracking import tracking_manager

logger = logging.getLogger(__name__)

geraet_router = APIRouter(prefix="/geraete", tags=["ortungsgeraete"])
org_router = APIRouter(prefix="/org/geraete", tags=["ortungsgeraete"])

CREATED = "org.geraet.created"
UPDATED = "org.geraet.updated"
CODE_ROTATED = "org.geraet.code_rotated"
DELETED = "org.geraet.deleted"
EINGERICHTET = "geraet.eingerichtet"

_NICHT_GEFUNDEN = "Nicht gefunden"


# ── Geräte-API ─────────────────────────────────────────────────────────────


async def _geraet_aus_token(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Ortungsgeraet:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Gerätetoken fehlt")
    token = authorization[len("Bearer "):].strip()
    geraet = (
        await db.execute(
            select(Ortungsgeraet)
            .where(Ortungsgeraet.token_hash == og.hash(token), Ortungsgeraet.aktiv.is_(True))
        )
    ).scalar_one_or_none()
    if geraet is None:
        raise HTTPException(status_code=401, detail="Gerät unbekannt")
    return geraet


async def _laufende_konvois(db: AsyncSession, geraet: Ortungsgeraet) -> list[uuid.UUID]:
    """Konvois der eigenen Organisation mit Status ``active``/``running``, in
    denen das gekoppelte Fahrzeug eingeplant ist (E7)."""
    if geraet.vehicle_id is None:
        return []
    rows = await db.execute(
        select(ConvoyVehicle.convoy_id)
        .join(Convoy, Convoy.id == ConvoyVehicle.convoy_id)
        .where(
            ConvoyVehicle.vehicle_id == geraet.vehicle_id,
            Convoy.organization_id == geraet.organization_id,
            Convoy.status.in_(og.LAUFEND),
        )
        .order_by(Convoy.created_at)
    )
    return list(rows.scalars().all())


async def _anweisung(db: AsyncSession, geraet: Ortungsgeraet, jetzt: datetime) -> dict[str, Any]:
    konvois = await _laufende_konvois(db, geraet)
    gesperrt = await org_plan.ist_gesperrt(db, geraet.organization_id)
    modus = og.modus(geraet.vehicle_id is not None, len(konvois), gesperrt)
    # Was das Gerät damit tut — nur im Stand, nur mit Akku —, entscheidet es
    # selbst; die Adresse zeigt auf diese Instanz (services/firmware_angebot.py).
    firmware = await firmware_angebot.fuer_geraet(geraet.kanal, geraet.firmware, geraet.hardware)
    return og.anweisung(modus, jetzt, firmware=firmware)


def _zustand_merken(geraet: Ortungsgeraet, daten: dict[str, Any], jetzt: datetime) -> None:
    geraet.zuletzt_gesehen = jetzt
    felder = og.zustand_lesen(daten)
    geraet.akku_seit = og.akku_seit(geraet.extern, geraet.akku_seit, felder.get("extern"), jetzt)
    for feld, wert in felder.items():
        setattr(geraet, feld, wert)


@geraet_router.post(
    "/einloesen",
    dependencies=[Depends(rate_limit("geraete_einloesen", 20, 900, count_attempts=True))],
)
async def einloesen(
    request: Request,
    daten: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Einmal-Code gegen das Gerätetoken tauschen. Jede Ablehnung ist dieselbe 404."""
    jetzt = datetime.now(timezone.utc)
    code = daten.get("code")
    hardware_id = str(daten.get("hardware_id") or "").strip()[:64]
    if not isinstance(code, str) or not hardware_id:
        raise HTTPException(status_code=404, detail=_NICHT_GEFUNDEN)
    normiert = og.code_normalisieren(code)
    if normiert is None:
        raise HTTPException(status_code=404, detail=_NICHT_GEFUNDEN)
    geraet = (
        await db.execute(
            select(Ortungsgeraet).where(
                Ortungsgeraet.code_hash == og.hash(normiert), Ortungsgeraet.aktiv.is_(True)
            )
        )
    ).scalar_one_or_none()
    if geraet is None or not og.code_gueltig(geraet.code_hash, geraet.code_expires_at, code, jetzt):
        raise HTTPException(status_code=404, detail=_NICHT_GEFUNDEN)
    token = og.token_erzeugen()
    geraet.token_hash = og.hash(token)
    geraet.code_hash = None
    geraet.code_expires_at = None
    geraet.eingerichtet_at = jetzt
    geraet.hardware_id = hardware_id
    hardware = daten.get("hardware")
    geraet.hardware = hardware.strip()[:40] if isinstance(hardware, str) and hardware.strip() else None
    _zustand_merken(geraet, daten, jetzt)
    await db.commit()
    await audit.record(
        db, EINGERICHTET, request=request, org_id=geraet.organization_id,
        target_type="ortungsgeraet", target_id=str(geraet.id),
        detail={"hardware_id": hardware_id, "firmware": geraet.firmware},
    )
    return {"geraet_id": str(geraet.id), "token": token}


@geraet_router.post("/hallo")
async def hallo(
    daten: dict[str, Any] = Body(default_factory=dict),
    geraet: Ortungsgeraet = Depends(_geraet_aus_token),
    db: AsyncSession = Depends(get_db),
):
    jetzt = datetime.now(timezone.utc)
    _zustand_merken(geraet, daten, jetzt)
    antwort = await _anweisung(db, geraet, jetzt)
    # Wurzeln nur hier: das Gerät meldet seinen Fingerabdruck in `hallo`, und ein
    # Bündel in jeder Antwort auf `positionen` kostete alle 30 s bis zu 12 KB.
    gemeldet = tw.gemeldet_lesen(daten)
    if gemeldet is not None:
        geraet.wurzeln_sha256 = gemeldet
    antwort["wurzeln"] = tw.angebot(gemeldet, tw.gewuenscht())
    await db.commit()
    return antwort


@geraet_router.post("/positionen")
async def positionen(
    daten: dict[str, Any] = Body(...),
    geraet: Ortungsgeraet = Depends(_geraet_aus_token),
    db: AsyncSession = Depends(get_db),
):
    jetzt = datetime.now(timezone.utc)
    try:
        fixes, verworfen = og.fixes_lesen(daten.get("fixes"), jetzt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _zustand_merken(geraet, daten, jetzt)
    antwort = await _anweisung(db, geraet, jetzt)
    if antwort["modus"] != "senden":
        # Kein Ort für die Position: das Gerät erfährt es aus der Antwort und
        # hört auf. Was schon unterwegs war, zählt als verworfen.
        verworfen += len(fixes)
        fixes = []
    ereignisse: list[tuple[str, dict[str, Any]]] = []
    if fixes:
        for convoy_id in await _laufende_konvois(db, geraet):
            ereignisse += await _eintragen(db, convoy_id, geraet.vehicle_id, fixes)
    await db.commit()
    for convoy_id, nachricht in ereignisse:
        await tracking_manager.broadcast(convoy_id, nachricht)
    return {"angenommen": len(fixes), "verworfen": verworfen, **antwort}


async def _eintragen(
    db: AsyncSession, convoy_id: uuid.UUID, vehicle_id: uuid.UUID, fixes: list[og.Fix]
) -> list[tuple[str, dict[str, Any]]]:
    """Fixes in einen Konvoi schreiben; gibt zurück, was danach zu verteilen ist."""
    if tracking_manager.is_recently_cleared(str(convoy_id), str(vehicle_id)):
        return []
    cv = await db.get(ConvoyVehicle, (convoy_id, vehicle_id))
    if cv is None:
        return []
    # Die Führung hat für dieses Fahrzeug das Telefon gelten lassen: verworfen.
    if not positionsquelle.tracker_sendet(str(convoy_id), str(vehicle_id), cv.tracker_uebersteuert_at):
        return []
    juengster = fixes[-1]
    stmt = pg_insert(VehiclePosition).values(
        convoy_id=convoy_id, vehicle_id=vehicle_id, lat=juengster.lat, lon=juengster.lon,
        speed_kmh=juengster.speed_kmh, heading=juengster.heading, recorded_at=juengster.t,
        quelle="tracker",
    )
    # Nur, wenn der Fix jünger ist als die vorhandene Position: ein
    # nachgereichtes Bündel aus dem Funkloch setzt das Fahrzeug nicht zurück.
    stmt = stmt.on_conflict_do_update(
        index_elements=["convoy_id", "vehicle_id"],
        set_={
            "lat": stmt.excluded.lat, "lon": stmt.excluded.lon,
            "speed_kmh": stmt.excluded.speed_kmh, "heading": stmt.excluded.heading,
            "recorded_at": stmt.excluded.recorded_at, "quelle": stmt.excluded.quelle,
        },
        where=VehiclePosition.recorded_at < stmt.excluded.recorded_at,
    )
    await db.execute(stmt)
    # Der Verlauf bekommt jeden Fix mit seiner GNSS-Zeit; ausgedünnt wird dort.
    for fix in fixes:
        await positionsverlauf.aufzeichnen(db, convoy_id, vehicle_id, fix.lat, fix.lon, jetzt=fix.t)
    ereignisse: list[tuple[str, dict[str, Any]]] = [(
        str(convoy_id),
        {
            "type": "position", "vehicle_id": str(vehicle_id),
            "lat": juengster.lat, "lon": juengster.lon,
            "speed_kmh": juengster.speed_kmh, "heading": juengster.heading,
            "quelle": "tracker",
        },
    )]
    if cv.vehicle_status == "planned":
        cv.vehicle_status = "en_route"
        cv.status_changed_at = datetime.now(timezone.utc)
        alarm_quittung.zuruecksetzen(cv)
        ereignisse.append((
            str(convoy_id),
            {
                "type": "status_update", "vehicle_id": str(vehicle_id),
                "vehicle_status": "en_route", "status_level": None, "status_note": None,
            },
        ))
    return ereignisse


_VERSION_IM_PFAD = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?$")


@geraet_router.get("/firmware/{kanal}/{version}.bin")
async def firmware_laden(
    kanal: str,
    version: str,
    geraet: Ortungsgeraet = Depends(_geraet_aus_token),
):
    """Das Image, das die Anweisung angeboten hat — geprüft, von dieser Instanz.

    Nur die Version aus dem aktuellen Manifest des Kanals; alles andere ist 404.
    ``FileResponse`` beantwortet ``Range``, damit ein abgebrochener Download im
    Funkloch fortgesetzt werden kann.
    """
    if kanal not in og.KANAELE or not _VERSION_IM_PFAD.match(version):
        raise HTTPException(status_code=404, detail=_NICHT_GEFUNDEN)
    pfad = await firmware_angebot.ablage.datei(kanal, version)
    if pfad is None:
        raise HTTPException(status_code=404, detail=_NICHT_GEFUNDEN)
    return FileResponse(pfad, media_type="application/octet-stream", filename=f"{version}.bin")


@geraet_router.post("/firmware/ergebnis")
async def firmware_ergebnis(
    daten: dict[str, Any] = Body(...),
    geraet: Ortungsgeraet = Depends(_geraet_aus_token),
    db: AsyncSession = Depends(get_db),
):
    jetzt = datetime.now(timezone.utc)
    ergebnis = daten.get("ergebnis")
    version = daten.get("version")
    if ergebnis not in og.UPDATE_ERGEBNISSE or not isinstance(version, str) or not version.strip():
        raise HTTPException(status_code=400, detail="version und ergebnis erwartet")
    meldung = daten.get("meldung")
    geraet.update_version = version.strip()[:40]
    geraet.update_ergebnis = ergebnis
    geraet.update_meldung = meldung.strip()[:200] if isinstance(meldung, str) and meldung.strip() else None
    geraet.update_at = jetzt
    _zustand_merken(geraet, daten, jetzt)
    antwort = await _anweisung(db, geraet, jetzt)
    await db.commit()
    return antwort


# ── Org-Admin ──────────────────────────────────────────────────────────────


class GeraetDaten(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    vehicle_id: uuid.UUID | None = None
    kanal: str = "stable"
    aktiv: bool = True


class GeraetZeile(BaseModel):
    id: uuid.UUID
    name: str
    vehicle_id: uuid.UUID | None
    vehicle_name: str | None
    kanal: str
    aktiv: bool
    eingerichtet: bool
    code_offen: bool
    hardware_id: str | None
    hardware: str | None
    firmware: str | None
    zuletzt_gesehen: datetime | None
    akku_prozent: int | None
    extern: bool | None
    akku_seit: datetime | None
    signal_dbm: int | None
    akku_niedrig: bool
    update_version: str | None
    update_ergebnis: str | None
    update_meldung: str | None
    update_at: datetime | None
    # Version, die die Instanz dem Gerät auf seinem Kanal anbietet — aus dem
    # Zwischenspeicher, die Liste holt nichts nach.
    angebot_version: str | None
    # Hat das Gerät die Wurzeln übernommen, die die Instanz verteilt?
    # None: die Instanz verwaltet keine (``TRACKER_WURZELN`` leer).
    wurzeln_aktuell: bool | None
    created_at: datetime


class GeraetMitCode(GeraetZeile):
    code: str
    code_expires_at: datetime


def _require_admin(role: str) -> None:
    if ROLE_ORDER.get(role, -1) < ROLE_ORDER["admin"]:
        raise HTTPException(status_code=403, detail="Org-Adminrechte erforderlich")


def _zeile(g: Ortungsgeraet, jetzt: datetime) -> dict[str, Any]:
    return {
        "id": g.id,
        "name": g.name,
        "vehicle_id": g.vehicle_id,
        "vehicle_name": g.vehicle.name if g.vehicle else None,
        "kanal": g.kanal,
        "aktiv": g.aktiv,
        "eingerichtet": g.token_hash is not None,
        "code_offen": g.code_hash is not None and g.code_expires_at is not None and g.code_expires_at > jetzt,
        "hardware_id": g.hardware_id,
        "hardware": g.hardware,
        "firmware": g.firmware,
        "zuletzt_gesehen": g.zuletzt_gesehen,
        "akku_prozent": g.akku_prozent,
        "extern": g.extern,
        "akku_seit": g.akku_seit,
        "signal_dbm": g.signal_dbm,
        "akku_niedrig": og.akku_niedrig(g.akku_prozent, g.extern),
        "update_version": g.update_version,
        "update_ergebnis": g.update_ergebnis,
        "update_meldung": g.update_meldung,
        "update_at": g.update_at,
        "angebot_version": firmware_angebot.angebot_bekannt(g.kanal, g.firmware, g.hardware),
        "wurzeln_aktuell": tw.aktuell(g.wurzeln_sha256, tw.gewuenscht()),
        "created_at": g.created_at,
    }


async def _laden(db: AsyncSession, org_id: uuid.UUID, geraet_id: uuid.UUID) -> Ortungsgeraet:
    g = (
        await db.execute(
            select(Ortungsgeraet)
            .where(Ortungsgeraet.id == geraet_id, Ortungsgeraet.organization_id == org_id)
            .options(selectinload(Ortungsgeraet.vehicle))
        )
    ).scalar_one_or_none()
    if g is None:
        raise HTTPException(status_code=404, detail=_NICHT_GEFUNDEN)
    return g


async def _felder_setzen(db: AsyncSession, org_id: uuid.UUID, g: Ortungsgeraet, d: GeraetDaten) -> None:
    if d.kanal not in og.KANAELE:
        raise HTTPException(status_code=422, detail="Unbekannter Kanal")
    if d.vehicle_id is not None:
        fahrzeug = await db.get(Vehicle, d.vehicle_id)
        # Fremd und unbekannt gleich: ob es das Fahrzeug woanders gibt, geht
        # niemanden an.
        if fahrzeug is None or fahrzeug.org_id != org_id:
            raise HTTPException(status_code=422, detail="Unbekanntes Fahrzeug")
        anderes = (
            await db.execute(
                select(Ortungsgeraet.id).where(
                    Ortungsgeraet.vehicle_id == d.vehicle_id, Ortungsgeraet.id != g.id
                )
            )
        ).scalar_one_or_none()
        if anderes is not None:
            raise HTTPException(status_code=409, detail="An diesem Fahrzeug hängt schon ein Tracker")
    g.name = d.name.strip()
    g.vehicle_id = d.vehicle_id
    g.kanal = d.kanal
    g.aktiv = d.aktiv


def _code_setzen(g: Ortungsgeraet, jetzt: datetime) -> str:
    """Neuer Einmal-Code; ein bestehendes Token gilt ab sofort nicht mehr."""
    code = og.code_erzeugen()
    g.code_hash = og.hash(code)
    g.code_expires_at = jetzt + og.CODE_GUELTIG
    g.token_hash = None
    g.eingerichtet_at = None
    return code


@org_router.get("", response_model=list[GeraetZeile])
async def liste(ctx: OrgCtx = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    _, org, role = ctx
    _require_admin(role)
    jetzt = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(Ortungsgeraet)
            .where(Ortungsgeraet.organization_id == org.id)
            .options(selectinload(Ortungsgeraet.vehicle))
            .order_by(Ortungsgeraet.created_at)
        )
    ).scalars().all()
    return [_zeile(g, jetzt) for g in rows]


@org_router.post("", response_model=GeraetMitCode, status_code=201)
async def anlegen(
    data: GeraetDaten,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    _require_admin(role)
    jetzt = datetime.now(timezone.utc)
    g = Ortungsgeraet(organization_id=org.id, name=data.name, created_by_id=user.id)
    await _felder_setzen(db, org.id, g, data)
    code = _code_setzen(g, jetzt)
    db.add(g)
    await db.commit()
    g = await _laden(db, org.id, g.id)
    await audit.record(
        db, CREATED, request=request, actor_id=user.id, actor_email=user.email,
        org_id=org.id, target_type="ortungsgeraet", target_id=str(g.id),
        detail={"vehicle_id": str(g.vehicle_id) if g.vehicle_id else None, "kanal": g.kanal},
    )
    return {**_zeile(g, jetzt), "code": code, "code_expires_at": g.code_expires_at}


@org_router.put("/{geraet_id}", response_model=GeraetZeile)
async def aendern(
    geraet_id: uuid.UUID,
    data: GeraetDaten,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    _require_admin(role)
    g = await _laden(db, org.id, geraet_id)
    await _felder_setzen(db, org.id, g, data)
    await db.commit()
    g = await _laden(db, org.id, geraet_id)
    await audit.record(
        db, UPDATED, request=request, actor_id=user.id, actor_email=user.email,
        org_id=org.id, target_type="ortungsgeraet", target_id=str(g.id),
        detail={"vehicle_id": str(g.vehicle_id) if g.vehicle_id else None, "kanal": g.kanal, "aktiv": g.aktiv},
    )
    return _zeile(g, datetime.now(timezone.utc))


@org_router.post("/{geraet_id}/code", response_model=GeraetMitCode)
async def code_erneuern(
    geraet_id: uuid.UUID,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Neuer Einmal-Code zum erneuten Einrichten; das alte Token gilt sofort nicht mehr."""
    user, org, role = ctx
    _require_admin(role)
    jetzt = datetime.now(timezone.utc)
    g = await _laden(db, org.id, geraet_id)
    code = _code_setzen(g, jetzt)
    await db.commit()
    g = await _laden(db, org.id, geraet_id)
    await audit.record(
        db, CODE_ROTATED, request=request, actor_id=user.id, actor_email=user.email,
        org_id=org.id, target_type="ortungsgeraet", target_id=str(g.id),
    )
    return {**_zeile(g, jetzt), "code": code, "code_expires_at": g.code_expires_at}


@org_router.delete("/{geraet_id}", status_code=204)
async def loeschen(
    geraet_id: uuid.UUID,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    _require_admin(role)
    g = await _laden(db, org.id, geraet_id)
    await db.delete(g)
    await db.commit()
    await audit.record(
        db, DELETED, request=request, actor_id=user.id, actor_email=user.email,
        org_id=org.id, target_type="ortungsgeraet", target_id=str(geraet_id),
    )
