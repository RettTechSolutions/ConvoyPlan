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

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import OrgCtx, get_org_context
from app.api.guards import ROLE_ORDER
from app.database import get_db
from app.models.convoy import Convoy
from app.models.public_tracker import PublicTracker, PublicTrackerConvoy
from app.services import aktionsseite, audit, positionsverlauf

public_router = APIRouter(prefix="/public/aktion", tags=["aktionsseite"])
org_router = APIRouter(prefix="/org/aktionsseiten", tags=["aktionsseite"])

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


@public_router.get("/{slug}", response_model=OeffentlicheAktion)
async def abrufen(
    slug: str,
    response: Response,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    token = _token_aus(authorization)
    jetzt = datetime.now(timezone.utc)
    treffer = _cache.get(slug)
    if treffer is not None:
        nutz, erzeugt, token_hash, gueltig_bis = treffer
        if time.monotonic() - erzeugt < _CACHE_TTL_S and (gueltig_bis is None or gueltig_bis > jetzt):
            if not _passt(token, token_hash):
                raise HTTPException(status_code=404, detail=_NICHT_GEFUNDEN)
            response.headers["Cache-Control"] = "private, max-age=60"
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
    ):
        raise HTTPException(status_code=404, detail=_NICHT_GEFUNDEN)

    nutz = OeffentlicheAktion.model_validate(
        await aktionsseite.nutzlast(db, tracker, jetzt)
    ).model_dump(mode="json")
    _cache[slug] = (nutz, time.monotonic(), tracker.fetch_token_hash, tracker.valid_until)
    response.headers["Cache-Control"] = "private, max-age=60"
    return nutz


# ── Verwaltung im Org-Admin ───────────────────────────────────────────────


def _require_admin(role: str) -> None:
    if ROLE_ORDER.get(role, -1) < ROLE_ORDER["admin"]:
        raise HTTPException(status_code=403, detail="Org-Adminrechte erforderlich")


class KonvoiEintrag(BaseModel):
    convoy_id: uuid.UUID
    display_name: str = Field(min_length=1, max_length=100)
    destination_label: str | None = Field(default=None, max_length=100)
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
    t.convoys.clear()
    await db.flush()
    for nr, e in enumerate(eintraege):
        t.convoys.append(
            PublicTrackerConvoy(
                convoy_id=e.convoy_id,
                display_name=e.display_name,
                destination_label=e.destination_label,
                color=e.color,
                position=nr,
            )
        )


def _felder_setzen(t: PublicTracker, d: AktionsseiteDaten) -> None:
    t.title = d.title
    t.subtitle = d.subtitle
    t.facts = d.facts
    t.theme = d.theme
    t.delay_minutes = d.delay_minutes
    t.show_destination = d.show_destination
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
