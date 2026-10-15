"""Öffentliche Aktionsseiten: Abruf durch den EventTracker, Verwaltung im Org-Admin.

Zwei Router in einer Datei, wie bei den Plänen: was die Organisation einstellt
und was davon hinausgeht, gehört zusammen gelesen. Die Regeln — Verzögerung,
Vergröberung, Positivliste — stehen in ``services/aktionsseite.py``.

Ausgeliefert wird die Seite nicht von dieser Instanz, sondern von einer
eigenen Anwendung (Convoyplan-EventTracker). Die holt ``GET /api/public/
aktion/{slug}`` mit ihrem Abruf-Token ab, einmal pro Minute, egal wie viele
Leute zuschauen. Diese Instanz sieht den Andrang nie, und der EventTracker
sieht nie eine Echtzeitposition.

Unbekannt, abgeschaltet, abgelaufen oder falsches Token: dieselbe 404. Keine
Antwort verrät, dass es einen Slug gibt.
"""
import hashlib
import hmac
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import OrgCtx, get_org_context, require_modul
from app.api.guards import ROLE_ORDER
from app.database import get_db
from app.models.convoy import Convoy
from app.models.public_tracker import (
    PublicTracker,
    PublicTrackerConvoy,
    PublicTrackerPhoto,
    PublicTrackerPhotoData,
    PublicTrackerPost,
)
from app.services import aktionsseite, aktionsseite_video, audit, org_module, positionsverlauf

public_router = APIRouter(prefix="/public/aktion", tags=["aktionsseite"])
org_router = APIRouter(
    prefix="/org/aktionsseiten",
    tags=["aktionsseite"],
    dependencies=[Depends(require_modul(org_module.AKTIONSSEITEN))],
)

CREATED = "org.aktionsseite.created"
UPDATED = "org.aktionsseite.updated"
DELETED = "org.aktionsseite.deleted"
TOKEN_ROTATED = "org.aktionsseite.token_rotated"

THEMES = ("neutral", "weihnachten")
_NICHT_GEFUNDEN = "Nicht gefunden"


# ── Öffentliche Antwort: die Positivliste ─────────────────────────────────
#
# ``extra="forbid"`` an jedem Modell: Ein Feld, das ``nutzlast`` zusätzlich
# lieferte, ließe die Antwort scheitern, statt still hinauszugehen.


class _Streng(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OeffentlichePosition(_Streng):
    lat: float
    lon: float
    coarse: bool
    at: datetime


class OeffentlicherPunkt(_Streng):
    lat: float
    lon: float


class OeffentlichesBild(_Streng):
    id: str
    width: int
    height: int


class OeffentlicherLink(_Streng):
    """Ein Link statt Bildern (§ 11): bereinigt, nur bekannte Dienste."""

    url: str
    dienst: Literal["instagram", "youtube", "facebook", "tiktok"]
    # Vorschaubild des Dienstes (§ 11.2), einmal beim Eingang geholt und neu
    # kodiert; ausgeliefert über denselben Bildendpunkt wie die Fotos.
    vorschau: OeffentlichesBild | None


class OeffentlichesVideo(_Streng):
    """Ein Video (§ 15): neu kodiert, ohne Metadaten, höchstens 60 s. Das
    Standbild kommt über den Bildendpunkt, das Video über ``/video/{id}.mp4``."""

    id: str
    width: int
    height: int
    seconds: float
    # Ton ist drin; abgespielt wird stumm, bis jemand ihn einschaltet.
    sound: bool
    poster: OeffentlichesBild


class OeffentlicherBeitrag(_Streng):
    """Ein freigegebenes Foto, Album oder ein Link — platziert und
    zurückgehalten nach ``beitrag_position``/``beitrag_sichtbar``. Absender,
    Prüfer und die Bildunterschrift aus Telegram gehen nie hinaus."""

    id: str
    at: datetime
    position: OeffentlicherPunkt | None
    coarse: bool
    text: str | None
    photos: list[OeffentlichesBild]
    link: OeffentlicherLink | None
    video: OeffentlichesVideo | None


class OeffentlicherKonvoi(_Streng):
    key: str
    name: str
    destination: str | None
    destination_point: OeffentlicherPunkt | None
    color: str | None
    status: str
    position: OeffentlichePosition | None
    trail: list[list[float]]
    driven_km: float
    total_km: float | None
    # Wie viele Fahrzeuge eingeplant sind — die Zahl, kein Fahrzeug selbst.
    # Der EventTracker zeichnet so viele hintereinander.
    vehicles: int
    posts: list[OeffentlicherBeitrag]


class OeffentlicheAktion(_Streng):
    title: str
    subtitle: str | None
    facts: str | None
    theme: str
    delay_minutes: int
    as_of: datetime
    generated_at: datetime
    valid_until: datetime | None
    convoys: list[OeffentlicherKonvoi]


# Antwort je Slug, höchstens eine Minute alt. Zusammen mit dem Hash, damit ein
# erneuertes Token sofort gilt, und dem Ablauf der Seite.
_CACHE_TTL_S = 60.0
_cache: dict[str, tuple[dict, float, str, datetime | None]] = {}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _token_aus(authorization: str | None) -> str | None:
    if not authorization:
        return None
    art, _, wert = authorization.partition(" ")
    return wert.strip() if art.lower() == "bearer" and wert.strip() else None


def _vergessen(slug: str) -> None:
    _cache.pop(slug, None)
    positionsverlauf.vergessen()


def _passt(token: str | None, token_hash: str) -> bool:
    return token is not None and hmac.compare_digest(_hash(token), token_hash)


async def _oeffentlich(slug: str, authorization: str | None, db: AsyncSession) -> dict:
    """Die öffentliche Antwort einer Seite — oder dieselbe 404 für alles."""
    token = _token_aus(authorization)
    jetzt = datetime.now(timezone.utc)
    treffer = _cache.get(slug)
    if treffer is not None:
        nutz, erzeugt, token_hash, gueltig_bis = treffer
        if time.monotonic() - erzeugt < _CACHE_TTL_S and (gueltig_bis is None or gueltig_bis > jetzt):
            if not _passt(token, token_hash):
                raise HTTPException(status_code=404, detail=_NICHT_GEFUNDEN)
            return nutz

    tracker = (
        await db.execute(
            select(PublicTracker)
            .where(PublicTracker.slug == slug)
            .options(selectinload(PublicTracker.convoys))
        )
    ).scalar_one_or_none()
    if (
        tracker is None
        or not aktionsseite.ist_aktiv(tracker, jetzt)
        or not _passt(token, tracker.fetch_token_hash)
        or not await org_module.freigegeben(db, tracker.organization_id, org_module.AKTIONSSEITEN)
    ):
        raise HTTPException(status_code=404, detail=_NICHT_GEFUNDEN)

    nutz = OeffentlicheAktion.model_validate(
        await aktionsseite.nutzlast(db, tracker, jetzt)
    ).model_dump(mode="json")
    _cache[slug] = (nutz, time.monotonic(), tracker.fetch_token_hash, tracker.valid_until)
    return nutz


@public_router.get("/{slug}", response_model=OeffentlicheAktion)
async def abrufen(
    slug: str,
    response: Response,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    nutz = await _oeffentlich(slug, authorization, db)
    response.headers["Cache-Control"] = "private, max-age=60"
    return nutz


def _bilder(beitrag: dict) -> list[dict]:
    """Alle Bilder eines öffentlichen Beitrags: Fotos, Vorschau des Links,
    Standbild des Videos."""
    link, video = beitrag["link"], beitrag["video"]
    return (
        beitrag["photos"]
        + ([link["vorschau"]] if link and link["vorschau"] else [])
        + ([video["poster"]] if video else [])
    )


@public_router.get("/{slug}/bild/{bild_id}/{groesse}.webp")
async def bild(
    slug: str,
    bild_id: str,
    groesse: Literal["gross", "klein"],
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Ein Bild eines Beitrags — nur, wenn es gerade in der Antwort steht.

    Geprüft wird an genau der Antwort, die ``abrufen`` liefert, nicht mit
    einer eigenen Abfrage: Sonst ließe sich ein Bild vor seiner Zeit über die
    Kennung holen, sobald sie einmal bekannt ist. Alles andere ist dieselbe 404."""
    nutz = await _oeffentlich(slug, authorization, db)
    if not any(
        f["id"] == bild_id for k in nutz["convoys"] for p in k["posts"] for f in _bilder(p)
    ):
        raise HTTPException(status_code=404, detail=_NICHT_GEFUNDEN)
    daten = (await db.execute(
        select(PublicTrackerPhotoData)
        .join(PublicTrackerPhoto, PublicTrackerPhoto.id == PublicTrackerPhotoData.photo_id)
        .where(PublicTrackerPhoto.public_id == bild_id)
    )).scalar_one_or_none()
    if daten is None:
        raise HTTPException(status_code=404, detail=_NICHT_GEFUNDEN)
    return Response(
        content=daten.gross if groesse == "gross" else daten.klein,
        media_type="image/webp",
        # Ein freigegebenes Bild ändert sich nicht; zurückgezogen fällt es aus
        # der Antwort, und der EventTracker löscht seine Kopie.
        headers={"Cache-Control": "private, max-age=86400"},
    )


@public_router.get("/{slug}/video/{video_id}.mp4")
async def video(
    slug: str,
    video_id: str,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Ein Video eines Beitrags (§ 15) — wie die Bilder nur, solange es in der
    Antwort steht. Der EventTracker holt es einmal ganz und liefert es selbst
    aus; Teilabrufe braucht es hier nicht."""
    nutz = await _oeffentlich(slug, authorization, db)
    if not any(
        p["video"] and p["video"]["id"] == video_id for k in nutz["convoys"] for p in k["posts"]
    ):
        raise HTTPException(status_code=404, detail=_NICHT_GEFUNDEN)
    datei = aktionsseite_video.pfad(video_id)
    if not datei.is_file():
        raise HTTPException(status_code=404, detail=_NICHT_GEFUNDEN)
    return FileResponse(
        datei, media_type="video/mp4",
        headers={"Cache-Control": "private, max-age=86400"},
    )


# ── Verwaltung im Org-Admin ───────────────────────────────────────────────


def _require_admin(role: str) -> None:
    if ROLE_ORDER.get(role, -1) < ROLE_ORDER["admin"]:
        raise HTTPException(status_code=403, detail="Org-Adminrechte erforderlich")


class Zielpunkt(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class KonvoiEintrag(BaseModel):
    convoy_id: uuid.UUID
    display_name: str = Field(min_length=1, max_length=100)
    destination_label: str | None = Field(default=None, max_length=100)
    # Ohne Angabe gilt der letzte Wegpunkt des Konvois.
    destination_point: Zielpunkt | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class AktionsseiteDaten(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    subtitle: str | None = Field(default=None, max_length=300)
    facts: str | None = Field(default=None, max_length=2000)
    theme: str = "neutral"
    delay_minutes: int = Field(
        default=120,
        ge=aktionsseite.MIN_VERZOEGERUNG_MIN,
        le=aktionsseite.MAX_VERZOEGERUNG_MIN,
    )
    show_destination: bool = False
    show_sender: bool = True
    valid_until: datetime | None = None
    enabled: bool = True
    convoys: list[KonvoiEintrag] = Field(default_factory=list, max_length=10)

    @field_validator("theme")
    @classmethod
    def _theme(cls, v: str) -> str:
        if v not in THEMES:
            raise ValueError(f"Unbekanntes Thema (erlaubt: {', '.join(THEMES)})")
        return v

    @field_validator("convoys")
    @classmethod
    def _eindeutig(cls, v: list[KonvoiEintrag]) -> list[KonvoiEintrag]:
        if len({k.convoy_id for k in v}) != len(v):
            raise ValueError("Ein Konvoi ist doppelt eingetragen")
        return v


class KonvoiZeile(KonvoiEintrag):
    convoy_name: str


class AktionsseiteZeile(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    subtitle: str | None
    facts: str | None
    theme: str
    delay_minutes: int
    show_destination: bool
    show_sender: bool
    valid_until: datetime | None
    enabled: bool
    active: bool
    endpoint: str
    convoys: list[KonvoiZeile]
    created_at: datetime


class AktionsseiteMitToken(AktionsseiteZeile):
    # Nur unmittelbar nach dem Anlegen oder Erneuern — gespeichert ist der Hash.
    fetch_token: str


def _endpoint(request: Request, slug: str) -> str:
    return str(request.url_for("abrufen", slug=slug))


async def _laden(db: AsyncSession, org_id: uuid.UUID, tracker_id: uuid.UUID) -> PublicTracker:
    t = (
        await db.execute(
            select(PublicTracker)
            .where(PublicTracker.id == tracker_id, PublicTracker.organization_id == org_id)
            .options(selectinload(PublicTracker.convoys))
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="Aktionsseite nicht gefunden")
    return t


async def _konvoinamen(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await db.execute(select(Convoy.id, Convoy.name).where(Convoy.id.in_(ids)))
    return {i: n for i, n in rows.all()}


async def _zeile(db: AsyncSession, request: Request, t: PublicTracker) -> dict:
    namen = await _konvoinamen(db, [c.convoy_id for c in t.convoys])
    return {
        "id": t.id,
        "slug": t.slug,
        "title": t.title,
        "subtitle": t.subtitle,
        "facts": t.facts,
        "theme": t.theme,
        "delay_minutes": t.delay_minutes,
        "show_destination": t.show_destination,
        "show_sender": t.show_sender,
        "valid_until": t.valid_until,
        "enabled": t.enabled,
        "active": aktionsseite.ist_aktiv(t, datetime.now(timezone.utc)),
        "endpoint": _endpoint(request, t.slug),
        "convoys": [
            {
                "convoy_id": c.convoy_id,
                "convoy_name": namen.get(c.convoy_id, ""),
                "display_name": c.display_name,
                "destination_label": c.destination_label,
                "destination_point": (
                    {"lat": c.destination_lat, "lon": c.destination_lon}
                    if c.destination_lat is not None
                    else None
                ),
                "color": c.color,
            }
            for c in t.convoys
        ],
        "created_at": t.created_at,
    }


async def _konvois_setzen(
    db: AsyncSession, org_id: uuid.UUID, t: PublicTracker, eintraege: list[KonvoiEintrag]
) -> None:
    ids = [e.convoy_id for e in eintraege]
    if ids:
        eigene = set(
            (
                await db.execute(
                    select(Convoy.id).where(Convoy.id.in_(ids), Convoy.organization_id == org_id)
                )
            ).scalars().all()
        )
        if eigene != set(ids):
            # Fremde und unbekannte Konvois gleich behandeln: ob es einen
            # Konvoi in einer anderen Organisation gibt, geht niemanden an.
            raise HTTPException(status_code=422, detail="Unbekannter Konvoi")
    # Bleibende Konvois werden geändert, nicht ersetzt: An ihrer Zeile hängen
    # Telegram-Gruppen und Beiträge, und ein neuer Titel der Seite darf die
    # nicht löschen. Nur wer aus der Liste fällt, nimmt seine mit.
    bisher = {c.convoy_id: c for c in t.convoys}
    neu = []
    for nr, e in enumerate(eintraege):
        c = bisher.get(e.convoy_id) or PublicTrackerConvoy(convoy_id=e.convoy_id)
        c.display_name = e.display_name
        c.destination_label = e.destination_label
        c.destination_lat = e.destination_point.lat if e.destination_point else None
        c.destination_lon = e.destination_point.lon if e.destination_point else None
        c.color = e.color
        c.position = nr
        neu.append(c)
    t.convoys[:] = neu


def _felder_setzen(t: PublicTracker, d: AktionsseiteDaten) -> None:
    t.title = d.title
    t.subtitle = d.subtitle
    t.facts = d.facts
    t.theme = d.theme
    t.delay_minutes = d.delay_minutes
    t.show_destination = d.show_destination
    t.show_sender = d.show_sender
    t.valid_until = d.valid_until
    t.enabled = d.enabled


@org_router.get("", response_model=list[AktionsseiteZeile])
async def liste(
    request: Request, ctx: OrgCtx = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    _, org, role = ctx
    _require_admin(role)
    rows = (
        await db.execute(
            select(PublicTracker)
            .where(PublicTracker.organization_id == org.id)
            .options(selectinload(PublicTracker.convoys))
            .order_by(PublicTracker.created_at.desc())
        )
    ).scalars().all()
    return [await _zeile(db, request, t) for t in rows]


@org_router.post("", response_model=AktionsseiteMitToken, status_code=201)
async def anlegen(
    data: AktionsseiteDaten,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    _require_admin(role)
    token = secrets.token_urlsafe(32)
    t = PublicTracker(
        organization_id=org.id,
        slug=secrets.token_urlsafe(16),
        fetch_token_hash=_hash(token),
        created_by_id=user.id,
        convoys=[],
    )
    _felder_setzen(t, data)
    db.add(t)
    await db.flush()
    await _konvois_setzen(db, org.id, t, data.convoys)
    await db.commit()
    t = await _laden(db, org.id, t.id)
    await audit.record(
        db, CREATED, request=request, actor_id=user.id, actor_email=user.email,
        org_id=org.id, target_type="aktionsseite", target_id=str(t.id),
        detail={"delay_minutes": t.delay_minutes, "convoys": len(t.convoys)},
    )
    _vergessen(t.slug)
    return {**await _zeile(db, request, t), "fetch_token": token}


@org_router.put("/{tracker_id}", response_model=AktionsseiteZeile)
async def aendern(
    tracker_id: uuid.UUID,
    data: AktionsseiteDaten,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    _require_admin(role)
    t = await _laden(db, org.id, tracker_id)
    _felder_setzen(t, data)
    await _konvois_setzen(db, org.id, t, data.convoys)
    if not data.show_sender:
        # Abgeschaltet heißt auch: die schon gespeicherten Namen gehen (Plan § 14.4).
        await db.execute(
            update(PublicTrackerPost)
            .where(PublicTrackerPost.tracker_id == t.id, PublicTrackerPost.sender_name.is_not(None))
            .values(sender_name=None)
        )
    await db.commit()
    t = await _laden(db, org.id, tracker_id)
    await audit.record(
        db, UPDATED, request=request, actor_id=user.id, actor_email=user.email,
        org_id=org.id, target_type="aktionsseite", target_id=str(t.id),
        detail={"enabled": t.enabled, "delay_minutes": t.delay_minutes, "convoys": len(t.convoys)},
    )
    _vergessen(t.slug)
    return await _zeile(db, request, t)


@org_router.post("/{tracker_id}/token", response_model=AktionsseiteMitToken)
async def token_erneuern(
    tracker_id: uuid.UUID,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Neues Abruf-Token; das alte gilt sofort nicht mehr."""
    user, org, role = ctx
    _require_admin(role)
    t = await _laden(db, org.id, tracker_id)
    token = secrets.token_urlsafe(32)
    t.fetch_token_hash = _hash(token)
    await db.commit()
    t = await _laden(db, org.id, tracker_id)
    await audit.record(
        db, TOKEN_ROTATED, request=request, actor_id=user.id, actor_email=user.email,
        org_id=org.id, target_type="aktionsseite", target_id=str(t.id),
    )
    _vergessen(t.slug)
    return {**await _zeile(db, request, t), "fetch_token": token}


@org_router.delete("/{tracker_id}", status_code=204)
async def loeschen(
    tracker_id: uuid.UUID,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    _require_admin(role)
    t = await _laden(db, org.id, tracker_id)
    slug = t.slug
    await db.delete(t)
    await db.commit()
    await audit.record(
        db, DELETED, request=request, actor_id=user.id, actor_email=user.email,
        org_id=org.id, target_type="aktionsseite", target_id=str(tracker_id),
    )
    _vergessen(slug)
    return Response(status_code=204)


@org_router.get("/{tracker_id}/vorschau", response_model=OeffentlicheAktion)
async def vorschau(
    tracker_id: uuid.UUID,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Genau die Antwort, die der EventTracker bekäme — mit derselben
    Verzögerung. Wer hier eine Echtzeitposition sieht, hat einen Fehler gefunden."""
    _, org, role = ctx
    _require_admin(role)
    t = await _laden(db, org.id, tracker_id)
    return OeffentlicheAktion.model_validate(await aktionsseite.nutzlast(db, t))
