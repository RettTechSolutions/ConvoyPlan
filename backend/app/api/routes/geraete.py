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

Der dritte Router (``track_router``) nimmt Rahmen an, die die Begleit-App über BLE
vom Tracker holt und mit ihrem Fahrer-Link abliefert (E14, ``services/tracker_ble.py``).
Er ist **keine** fünfte Schreibstelle: Nach der Prüfung von Link, Signatur und
``seq`` läuft die Nutzlast durch dieselben Funktionen wie der direkte Aufruf
(``_hallo_verarbeiten``, ``_positionen_verarbeiten``), mit allen Regeln — Lizenz,
Plansperre, E7/E8, Positionsquelle, Alarmquittung. Der Pfad liegt unter
``/api/track/``, das der Lizenzwächter schon durchlässt; ohne Lizenz hört das Gerät
also auch über BLE ``schweigen`` statt 402.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import OrgCtx, get_org_context
from app.api.guards import ROLE_ORDER
from app.database import get_db
from app.middleware.license_guard import is_licensed
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.organization import Organization
from app.models.ortungsgeraet import Ortungsgeraet
from app.models.share_link import ConvoyShareLink
from app.models.vehicle import Vehicle
from app.models.vehicle_position import VehiclePosition
from app.services import alarm_quittung, audit, firmware_angebot, org_plan, positionsquelle, positionsverlauf
from app.services import share_links as share_links_svc
from app.services import tracker_ble as tb
from app.services import tracker_wurzeln as tw
from app.services import ortungsgeraet as og
from app.services.rate_limit import rate_limit, register_failure
from app.services.tracking import tracking_manager

logger = logging.getLogger(__name__)

geraet_router = APIRouter(prefix="/geraete", tags=["ortungsgeraete"])
org_router = APIRouter(prefix="/org/geraete", tags=["ortungsgeraete"])
track_router = APIRouter(prefix="/track", tags=["ortungsgeraete"])

CREATED = "org.geraet.created"
UPDATED = "org.geraet.updated"
CODE_ROTATED = "org.geraet.code_rotated"
DELETED = "org.geraet.deleted"
TAKT_UPDATED = "org.geraet.takt_updated"
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
    # Ohne Lizenz wie eine gesperrte Organisation: `schweigen`, und `positionen`
    # verwirft. Die Middleware lässt diese Pfade dafür durch (license_guard.py).
    gesperrt = await org_plan.ist_gesperrt(db, geraet.organization_id) or not await is_licensed()
    modus = og.modus(geraet.vehicle_id is not None, len(konvois), gesperrt)
    # Was das Gerät damit tut — nur im Stand, nur mit Akku —, entscheidet es
    # selbst; die Adresse zeigt auf diese Instanz (services/firmware_angebot.py).
    firmware = await firmware_angebot.fuer_geraet(geraet.kanal, geraet.firmware, geraet.hardware)
    buendel = (
        await db.execute(select(Organization.tracker_buendel_s).where(Organization.id == geraet.organization_id))
    ).scalar_one_or_none()
    return og.anweisung(modus, jetzt, firmware=firmware, buendel=buendel)


def _zustand_merken(geraet: Ortungsgeraet, daten: dict[str, Any], jetzt: datetime) -> None:
    geraet.zuletzt_gesehen = jetzt
    # Erwartet wird nur nach einem Bündel (``positionen`` setzt es neu): ein ``hallo``
    # kommt aus der Ruhe, ein Update-Ergebnis nach dem Neustart.
    geraet.unterbrochen_ab = None
    geraet.gps_gestoert_ab = None
    netz = og.netz_lesen(daten)
    if netz is not None:
        geraet.netz = netz
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
    # Ein neuer Schlüssel bei jedem Einlösen; `seq` zählt ab ihm von vorn.
    schluessel = tb.schluessel_erzeugen()
    geraet.schluessel = tb.ablegen(schluessel)
    geraet.ble_seq = None
    _zustand_merken(geraet, daten, jetzt)
    await db.commit()
    await audit.record(
        db, EINGERICHTET, request=request, org_id=geraet.organization_id,
        target_type="ortungsgeraet", target_id=str(geraet.id),
        detail={"hardware_id": hardware_id, "firmware": geraet.firmware},
    )
    return {"geraet_id": str(geraet.id), "token": token, "schluessel": tb.als_base64(schluessel)}


def _schluessel_angebot(geraet: Ortungsgeraet, daten: dict[str, Any]) -> str | None:
    """Der Geräteschlüssel für die Antwort auf ein **direktes** ``hallo``, sonst ``None``.

    Nur, wenn das Gerät eine Kennung meldet und sie abweicht. Ein Gerät von vor E14
    (eingerichtet ohne Schlüssel) meldet ``""`` und bekommt hier seinen ersten."""
    gemeldet = tb.kennung_gemeldet(daten)
    if gemeldet is None:
        return None
    schluessel = tb.schluessel_lesen(geraet.schluessel)
    if schluessel is None:
        schluessel = tb.schluessel_erzeugen()
        geraet.schluessel = tb.ablegen(schluessel)
        geraet.ble_seq = None
    return tb.als_base64(schluessel) if tb.angebot_noetig(gemeldet, schluessel) else None


async def _hallo_verarbeiten(
    db: AsyncSession, geraet: Ortungsgeraet, daten: dict[str, Any], jetzt: datetime, direkt: bool
) -> dict[str, Any]:
    """``hallo``, direkt oder weitergeleitet. Der Aufrufer schreibt fest (``commit``)."""
    _zustand_merken(geraet, daten, jetzt)
    antwort = await _anweisung(db, geraet, jetzt)
    # Wurzeln nur hier: das Gerät meldet seinen Fingerabdruck in `hallo`, und ein
    # Bündel in jeder Antwort auf `positionen` kostete alle 15 s bis zu 12 KB.
    gemeldet = tw.gemeldet_lesen(daten)
    if gemeldet is not None:
        geraet.wurzeln_sha256 = gemeldet
    if direkt:
        antwort["wurzeln"] = tw.angebot(gemeldet, tw.gewuenscht())
        antwort["schluessel"] = _schluessel_angebot(geraet, daten)
    else:
        # Über BLE nie: keine Firmware (der Download braucht das Gerätetoken, und das
        # geht nicht durchs Telefon), keine Wurzeln (TLS macht dort die App), und der
        # Schlüssel ginge durch genau die Leitung, die er absichern soll.
        antwort.update(firmware=None, wurzeln=None, schluessel=None)
    return antwort


@geraet_router.post("/hallo")
async def hallo(
    daten: dict[str, Any] = Body(default_factory=dict),
    geraet: Ortungsgeraet = Depends(_geraet_aus_token),
    db: AsyncSession = Depends(get_db),
):
    antwort = await _hallo_verarbeiten(db, geraet, daten, datetime.now(timezone.utc), direkt=True)
    await db.commit()
    return antwort


@geraet_router.post("/positionen")
async def positionen(
    daten: dict[str, Any] = Body(...),
    geraet: Ortungsgeraet = Depends(_geraet_aus_token),
    db: AsyncSession = Depends(get_db),
):
    antwort, ereignisse = await _positionen_verarbeiten(db, geraet, daten, datetime.now(timezone.utc))
    await db.commit()
    for convoy_id, nachricht in ereignisse:
        await tracking_manager.broadcast(convoy_id, nachricht)
    return antwort


async def _positionen_verarbeiten(
    db: AsyncSession, geraet: Ortungsgeraet, daten: dict[str, Any], jetzt: datetime
) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    """``positionen``, direkt oder weitergeleitet: die Antwort und was danach zu verteilen ist.

    Der Aufrufer schreibt fest und verteilt erst danach. Ein unbrauchbares Bündel wirft
    die 400, bevor irgendetwas am Gerät geändert ist."""
    try:
        fixes, verworfen = og.fixes_lesen(daten.get("fixes"), jetzt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    gps_alt = geraet.gps_gestoert_ab
    _zustand_merken(geraet, daten, jetzt)
    antwort = await _anweisung(db, geraet, jetzt)
    # Im Takt, den diese Antwort dem Gerät vorgibt (Sendetakt der Organisation).
    buendel = antwort["buendel_s"]
    geraet.unterbrochen_ab = og.unterbrochen_ab(antwort["modus"], daten.get("ruhe"), jetzt, buendel)
    geraet.gps_gestoert_ab = og.gps_gestoert_ab(gps_alt, geraet.unterbrochen_ab, len(fixes), jetzt, buendel)
    if antwort["modus"] != "senden":
        # Kein Ort für die Position: das Gerät erfährt es aus der Antwort und
        # hört auf. Was schon unterwegs war, zählt als verworfen.
        verworfen += len(fixes)
        fixes = []
    ereignisse: list[tuple[str, dict[str, Any]]] = []
    if fixes:
        for convoy_id in await _laufende_konvois(db, geraet):
            ereignisse += await _eintragen(db, convoy_id, geraet.vehicle_id, fixes)
    return {"angenommen": len(fixes), "verworfen": verworfen, **antwort}, ereignisse


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
    if kanal not in og.KANAELE or not firmware_angebot.ist_version(version):
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


# ── Weiterleitung über BLE und Bake (Fahrer-Link) ──────────────────────────


async def _fahrer_link(db: AsyncSession, slug: str, track_token: str | None) -> ConvoyShareLink | None:
    """Der Link, wenn er besteht, nicht widerrufen ist, ``driver`` erlaubt und — bei
    Passwort — das Sitzungstoken dazu stimmt. Sonst ``None``; der Aufrufer macht daraus
    dieselbe 404 wie aus jeder anderen Ablehnung."""
    link = (
        await db.execute(select(ConvoyShareLink).where(ConvoyShareLink.slug == slug))
    ).scalar_one_or_none()
    if link is None or link.revoked or link.scope != "driver":
        return None
    if link.password_hash is not None:
        token_slug = share_links_svc.decode_session_token(track_token) if track_token else None
        if token_slug != slug:
            return None
    return link


def _abgelehnt(request: Request, bucket: str) -> HTTPException:
    register_failure(request, bucket)
    return HTTPException(status_code=404, detail=_NICHT_GEFUNDEN)


@track_router.post(
    "/{slug}/tracker",
    dependencies=[Depends(rate_limit("track-tracker", max_attempts=20, window_seconds=300))],
)
async def weiterleiten(
    slug: str,
    request: Request,
    roh: Any = Body(default=None),
    x_track_token: str | None = Header(default=None, alias="X-Track-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Ein Rahmen vom Tracker, den die Begleit-App über BLE geholt hat.

    Link, Gerät der Organisation hinter dem Link und Signatur — fällt eines durch, ist es
    dieselbe 404, und sie zählt gegen das Rate-Limit. Eine schon angenommene ``seq`` ist
    409: die Wiederholung eines echten Rahmens, nicht verarbeitet. Sonst läuft die
    Nutzlast durch dieselben Funktionen wie der direkte Aufruf, mit ``netz: ble``, und
    die Antwort geht signiert zurück — auch ein 401 für ein gesperrtes Gerät und ein 400
    für einen unbrauchbaren Körper, denn beides muss das Gerät erfahren können.
    """
    bucket = "track-tracker"
    link = await _fahrer_link(db, slug, x_track_token)
    rahmen = tb.rahmen_lesen(roh)
    if link is None or rahmen is None:
        raise _abgelehnt(request, bucket)
    try:
        geraet_id = uuid.UUID(rahmen.geraet)
    except ValueError:
        raise _abgelehnt(request, bucket) from None
    # Das Gerät muss nicht in diesem Konvoi fahren, nur zur selben Organisation gehören.
    org_id = (
        await db.execute(select(Convoy.organization_id).where(Convoy.id == link.convoy_id))
    ).scalar_one_or_none()
    geraet = (
        await db.execute(
            select(Ortungsgeraet).where(Ortungsgeraet.id == geraet_id, Ortungsgeraet.organization_id == org_id)
        )
    ).scalar_one_or_none()
    abgelegt = geraet.schluessel if geraet is not None else None
    schluessel = tb.schluessel_lesen(abgelegt)
    if geraet is None or schluessel is None or not tb.rahmen_echt(schluessel, rahmen):
        raise _abgelehnt(request, bucket)

    # `seq` in einem Schritt prüfen und setzen. Leiten zwei Apps denselben Rahmen
    # gleichzeitig weiter, wartet die zweite auf die Zeilensperre der ersten, sieht
    # danach deren `seq` und bekommt 409 — verarbeitet wird er genau einmal.
    gesetzt = (
        await db.execute(
            update(Ortungsgeraet)
            .where(
                Ortungsgeraet.id == geraet_id,
                Ortungsgeraet.schluessel == abgelegt,
                or_(Ortungsgeraet.ble_seq.is_(None), Ortungsgeraet.ble_seq < rahmen.seq),
            )
            .values(ble_seq=rahmen.seq)
            .returning(Ortungsgeraet.id)
            .execution_options(synchronize_session=False)
        )
    ).scalar_one_or_none()
    if gesetzt is None:
        await db.rollback()
        # Dazwischen neu eingelöst (anderer Schlüssel) ist keine Wiederholung, sondern ein
        # Rahmen mit einem Schlüssel, der nicht mehr gilt.
        aktuell = (
            await db.execute(select(Ortungsgeraet.schluessel).where(Ortungsgeraet.id == geraet_id))
        ).scalar_one_or_none()
        if aktuell != abgelegt:
            raise _abgelehnt(request, bucket)
        raise HTTPException(status_code=409, detail="Rahmen schon angenommen")
    # Was wir oben gelesen haben, kann älter sein als die Sperre; ab hier gilt der Stand darunter.
    await db.refresh(geraet)

    jetzt = datetime.now(timezone.utc)
    ereignisse: list[tuple[str, dict[str, Any]]] = []
    daten = tb.nutzlast_lesen(rahmen)
    status = 200
    koerper: dict[str, Any]
    if not geraet.aktiv or geraet.token_hash is None:
        # Wie `_geraet_aus_token`: gesperrt oder neu einzurichten. Die `seq` bleibt
        # verbraucht, damit sich die Antwort nicht wieder abspielen lässt.
        status, koerper = 401, {"detail": "Gerät unbekannt"}
    elif daten is None:
        status, koerper = 400, {"detail": "Körper unbrauchbar"}
    else:
        daten = {**daten, "netz": "ble"}
        try:
            if rahmen.art == "hallo":
                koerper = await _hallo_verarbeiten(db, geraet, daten, jetzt, direkt=False)
            else:
                koerper, ereignisse = await _positionen_verarbeiten(db, geraet, daten, jetzt)
                koerper["firmware"] = None
        except HTTPException as e:
            status, koerper = e.status_code, {"detail": e.detail}
    await db.commit()
    for convoy_id, nachricht in ereignisse:
        await tracking_manager.broadcast(convoy_id, nachricht)
    return tb.antwort(schluessel, rahmen, status, koerper)


@track_router.get(
    "/{slug}/baken",
    dependencies=[Depends(rate_limit("track-baken", max_attempts=20, window_seconds=300))],
)
async def baken(
    slug: str,
    request: Request,
    x_track_token: str | None = Header(default=None, alias="X-Track-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Bake-Kennungen der Tracker an den Fahrzeugen dieses Konvois, für drei Fenster.

    Die App schlägt damit das Fahrzeug vor, in dem sie sitzt; belegt wird es erst, wenn
    die Besatzung es wählt (``belegen``). Nur Tracker der Organisation des Konvois, nur
    eingerichtete, freigegebene mit Schlüssel. Ohne Gerätekennung und ohne Namen."""
    link = await _fahrer_link(db, slug, x_track_token)
    if link is None:
        raise _abgelehnt(request, "track-baken")
    org_id = (
        await db.execute(select(Convoy.organization_id).where(Convoy.id == link.convoy_id))
    ).scalar_one_or_none()
    fahrzeuge = select(ConvoyVehicle.vehicle_id).where(ConvoyVehicle.convoy_id == link.convoy_id)
    geraete = (
        await db.execute(
            select(Ortungsgeraet).where(
                Ortungsgeraet.vehicle_id.in_(fahrzeuge),
                Ortungsgeraet.organization_id == org_id,
                Ortungsgeraet.aktiv.is_(True),
                Ortungsgeraet.token_hash.is_not(None),
                Ortungsgeraet.schluessel.is_not(None),
            )
        )
    ).scalars().all()
    jetzt = datetime.now(timezone.utc)
    eintraege = []
    for g in geraete:
        schluessel = tb.schluessel_lesen(g.schluessel)
        if schluessel is not None:
            eintraege.append({"vehicle_id": str(g.vehicle_id), "kennungen": tb.bake_kennungen(schluessel, jetzt)})
    return {"fenster_s": tb.FENSTER_S, "baken": eintraege}


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
    # Weg des letzten Aufrufs: wlan | mobil | ble; None: nie gemeldet.
    netz: str | None
    akku_niedrig: bool
    # Ab wann zwei erwartete Bündel ausgeblieben sind; None: keins erwartet.
    unterbrochen_ab: datetime | None
    # Ab wann Bündel ohne plausiblen Fix kommen (GPS gestört); None: nichts erwartet.
    gps_gestoert_ab: datetime | None
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
        "netz": g.netz,
        "akku_niedrig": og.akku_niedrig(g.akku_prozent, g.extern),
        "unterbrochen_ab": g.unterbrochen_ab,
        "gps_gestoert_ab": g.gps_gestoert_ab,
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


class TaktWahl(BaseModel):
    buendel_s: int
    # Geschätzt je Tracker und Fahrstunde, mit offener und ohne offene Verbindung.
    kb_pro_stunde: int
    kb_pro_stunde_ohne_keepalive: int


class Takt(BaseModel):
    buendel_s: int
    standard_s: int
    intervall_s: int
    wahl: list[TaktWahl]


class TaktDaten(BaseModel):
    buendel_s: int


def _takt(org: Organization) -> dict[str, Any]:
    return {
        "buendel_s": og.buendel_s(org.tracker_buendel_s),
        "standard_s": og.TAKT["buendel_s"],
        "intervall_s": og.TAKT["intervall_s"],
        "wahl": [
            {
                "buendel_s": b,
                "kb_pro_stunde": og.volumen_kb_pro_stunde(b),
                "kb_pro_stunde_ohne_keepalive": og.volumen_kb_pro_stunde(b, offen=False),
            }
            for b in og.BUENDEL_WAHL
        ],
    }


# Vor den Routen mit ``/{geraet_id}``, sonst hielte FastAPI „takt" für eine ID.
@org_router.get("/takt", response_model=Takt)
async def takt_lesen(ctx: OrgCtx = Depends(get_org_context)):
    """Wie oft die Tracker dieser Organisation in Fahrt senden, mit Volumenschätzung."""
    _, org, role = ctx
    _require_admin(role)
    return _takt(org)


@org_router.put("/takt", response_model=Takt)
async def takt_setzen(
    data: TaktDaten,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Gilt ab der nächsten Antwort an das Gerät, also spätestens nach einem Bündel."""
    user, org, role = ctx
    _require_admin(role)
    if data.buendel_s not in og.BUENDEL_WAHL:
        raise HTTPException(status_code=422, detail="Nicht wählbarer Sendetakt")
    vorher = og.buendel_s(org.tracker_buendel_s)
    org.tracker_buendel_s = data.buendel_s
    await db.commit()
    await audit.record(
        db, TAKT_UPDATED, request=request, actor_id=user.id, actor_email=user.email,
        org_id=org.id, target_type="organization", target_id=str(org.id),
        detail={"vorher": vorher, "nachher": data.buendel_s},
    )
    return _takt(org)


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
