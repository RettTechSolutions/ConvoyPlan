"""Org-Admin: Telegram-Bot, Gruppen und Presse der Aktionsseiten.

Plan: docs/superpowers/plans/2026-10-13-fotos-auf-der-aktionsseite.md, § 8.3
und § 8.4. Gearbeitet wird in Telegram; hier wird eingerichtet. Wie die übrigen
Aktionsseiten nur für Org-Admins und nur mit freigegebenem Modul.

Der Router muss **vor** ``aktionsseite.org_router`` eingehängt sein: dessen
``/{tracker_id}`` finge ``/telegram`` sonst ab und lehnte es als ungültige
UUID ab.
"""
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import OrgCtx, get_org_context, require_modul
from app.api.routes.aktionsseite import _laden, _require_admin, _vergessen
from app.database import get_db
from app.models.public_tracker import (
    BEITRAG_STATUS,
    PublicTrackerChat,
    PublicTrackerCode,
    BEITRAG_TEXT_MAX,
    PublicTrackerConvoy,
    PublicTrackerPhoto,
    PublicTrackerPhotoData,
    PublicTrackerPost,
    PublicTrackerPresse,
    PublicTrackerTelegram,
)
from app.services import aktionsseite_telegram as tg
from app.services import audit, org_module
from app.services.crypto import decrypt_secret, encrypt_secret
from app.services.telegram import TelegramFehler

router = APIRouter(
    prefix="/org/aktionsseiten",
    tags=["aktionsseite"],
    dependencies=[Depends(require_modul(org_module.AKTIONSSEITEN))],
)

BOT_GESETZT = "org.aktionsseite.telegram_bot_gesetzt"
BOT_ENTFERNT = "org.aktionsseite.telegram_bot_entfernt"
CODE_ERZEUGT = "org.aktionsseite.telegram_code"
GRUPPE_GETRENNT = "org.aktionsseite.telegram_getrennt"
PRESSE_ENTFERNT = "org.aktionsseite.presse_entfernt"


class BotStand(BaseModel):
    """Was der Org-Admin über den Bot sieht — nie den Token."""

    eingerichtet: bool
    bot_username: str | None = None
    # bereit · privat (sieht in Gruppen keine Fotos) · ungueltig · konflikt ·
    # fehler · ungeprueft
    status: str | None = None
    last_error: str | None = None
    checked_at: datetime | None = None


class BotToken(BaseModel):
    token: str = Field(min_length=20, max_length=100, pattern=r"^\d+:[A-Za-z0-9_-]+$")


class Code(BaseModel):
    code: str
    expires_at: datetime


class GruppeZeile(BaseModel):
    convoy_id: uuid.UUID
    chat_title: str | None
    thema: bool


class PresseZeile(BaseModel):
    telegram_user_id: int
    display_name: str
    username: str | None
    added_at: datetime


class SeiteTelegram(BaseModel):
    gruppen: list[GruppeZeile]
    presse: list[PresseZeile]


def _stand(bot: PublicTrackerTelegram | None) -> dict:
    if bot is None:
        return {"eingerichtet": False}
    return {
        "eingerichtet": True,
        "bot_username": bot.bot_username,
        "status": bot.status,
        "last_error": bot.last_error,
        "checked_at": bot.checked_at,
    }


@router.get("/telegram", response_model=BotStand)
async def bot_lesen(ctx: OrgCtx = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    _, org, role = ctx
    _require_admin(role)
    return _stand(await db.get(PublicTrackerTelegram, org.id))


@router.put("/telegram", response_model=BotStand)
async def bot_setzen(
    data: BotToken,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Token prüfen (``getMe``) und verschlüsselt ablegen. Angezeigt wird er nie wieder."""
    user, org, role = ctx
    _require_admin(role)
    try:
        ich = await tg.api_fuer(data.token).ich()
    except TelegramFehler as e:
        if e.code in (401, 404):
            raise HTTPException(status_code=422, detail="Telegram kennt diesen Token nicht.") from None
        raise HTTPException(status_code=502, detail="Telegram ist gerade nicht erreichbar.") from None
    bot = await db.get(PublicTrackerTelegram, org.id)
    neu = bot is None
    if neu:
        bot = PublicTrackerTelegram(organization_id=org.id)
        db.add(bot)
    bot.bot_token_enc = encrypt_secret(data.token)
    bot.bot_username = ich.username
    bot.status = "bereit" if ich.liest_alles else "privat"
    bot.last_error = None
    bot.checked_at = datetime.now(timezone.utc)
    # Ein anderer Bot fängt bei seinen eigenen Updates an.
    bot.update_offset = 0
    await db.commit()
    await audit.record(
        db, BOT_GESETZT, request=request, actor_id=user.id, actor_email=user.email,
        org_id=org.id, target_type="organization", target_id=str(org.id),
        detail={"bot": ich.username, "liest_alles": ich.liest_alles},
    )
    return _stand(bot)


@router.delete("/telegram", status_code=204)
async def bot_entfernen(
    request: Request, ctx: OrgCtx = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    """Der Bot fragt nicht mehr ab. Gruppen, Presse und Beiträge bleiben stehen."""
    user, org, role = ctx
    _require_admin(role)
    bot = await db.get(PublicTrackerTelegram, org.id)
    if bot is not None:
        await db.delete(bot)
        await db.commit()
        await audit.record(
            db, BOT_ENTFERNT, request=request, actor_id=user.id, actor_email=user.email,
            org_id=org.id, target_type="organization", target_id=str(org.id),
        )
    return Response(status_code=204)


@router.get("/{tracker_id}/telegram", response_model=SeiteTelegram)
async def seite_lesen(
    tracker_id: uuid.UUID, ctx: OrgCtx = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    _, org, role = ctx
    _require_admin(role)
    await _laden(db, org.id, tracker_id)
    gruppen = (await db.execute(
        select(PublicTrackerChat).where(PublicTrackerChat.tracker_id == tracker_id)
    )).scalars().all()
    presse = (await db.execute(
        select(PublicTrackerPresse)
        .where(PublicTrackerPresse.tracker_id == tracker_id)
        .order_by(PublicTrackerPresse.added_at)
    )).scalars().all()
    return {
        # Die Chat-ID bleibt drin: mit ihr allein kommt niemand in eine Gruppe,
        # aber sie gehört auch nirgends hin.
        "gruppen": [
            {"convoy_id": g.convoy_id, "chat_title": g.chat_title, "thema": g.thread_id is not None}
            for g in gruppen
        ],
        "presse": [
            {"telegram_user_id": p.telegram_user_id, "display_name": p.display_name,
             "username": p.username, "added_at": p.added_at}
            for p in presse
        ],
    }


async def _code_anlegen(
    db: AsyncSession, request: Request, ctx, tracker_id: uuid.UUID, art: str,
    convoy_id: uuid.UUID | None,
) -> dict:
    user, org, _ = ctx
    jetzt = datetime.now(timezone.utc)
    gueltig = tg.VERBINDEN_GUELTIG if art == "verbinden" else tg.PRESSE_GUELTIG
    if art == "verbinden":
        # Ein neuer Code ersetzt den alten dieses Konvois.
        await db.execute(delete(PublicTrackerCode).where(
            PublicTrackerCode.tracker_id == tracker_id,
            PublicTrackerCode.convoy_id == convoy_id,
            PublicTrackerCode.art == "verbinden",
        ))
    code = tg.code_erzeugen()
    db.add(PublicTrackerCode(
        code_hash=tg.code_hash(code), tracker_id=tracker_id, convoy_id=convoy_id, art=art,
        expires_at=jetzt + gueltig,
    ))
    await db.commit()
    await audit.record(
        db, CODE_ERZEUGT, request=request, actor_id=user.id, actor_email=user.email,
        org_id=org.id, target_type="aktionsseite", target_id=str(tracker_id),
        detail={"art": art, "convoy_id": str(convoy_id) if convoy_id else None},
    )
    return {"code": code, "expires_at": jetzt + gueltig}


@router.post("/{tracker_id}/konvois/{convoy_id}/telegram-code", response_model=Code)
async def verbinden_code(
    tracker_id: uuid.UUID,
    convoy_id: uuid.UUID,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Einmalcode, 15 min gültig: ``/verbinden CODE`` in die Gruppe oder das Thema."""
    _, org, role = ctx
    _require_admin(role)
    await _laden(db, org.id, tracker_id)
    if await db.get(PublicTrackerConvoy, (tracker_id, convoy_id)) is None:
        raise HTTPException(status_code=404, detail="Konvoi steht nicht auf dieser Aktionsseite")
    return await _code_anlegen(db, request, ctx, tracker_id, "verbinden", convoy_id)


@router.delete("/{tracker_id}/konvois/{convoy_id}/telegram", status_code=204)
async def trennen(
    tracker_id: uuid.UUID,
    convoy_id: uuid.UUID,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Keine neuen Beiträge mehr aus dieser Gruppe. Vorhandene bleiben (Plan § 9)."""
    user, org, role = ctx
    _require_admin(role)
    await _laden(db, org.id, tracker_id)
    await db.execute(delete(PublicTrackerChat).where(
        PublicTrackerChat.tracker_id == tracker_id, PublicTrackerChat.convoy_id == convoy_id
    ))
    await db.commit()
    await audit.record(
        db, GRUPPE_GETRENNT, request=request, actor_id=user.id, actor_email=user.email,
        org_id=org.id, target_type="aktionsseite", target_id=str(tracker_id),
        detail={"convoy_id": str(convoy_id)},
    )
    return Response(status_code=204)


@router.post("/{tracker_id}/presse-code", response_model=Code)
async def presse_code(
    tracker_id: uuid.UUID,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """24 h gültig, für mehrere Personen: privat an den Bot ``/presse CODE``."""
    _, org, role = ctx
    _require_admin(role)
    await _laden(db, org.id, tracker_id)
    return await _code_anlegen(db, request, ctx, tracker_id, "presse", None)


@router.delete("/{tracker_id}/presse/{telegram_user_id}", status_code=204)
async def presse_entfernen(
    tracker_id: uuid.UUID,
    telegram_user_id: int,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Wirkt sofort: Der nächste Knopfdruck bekommt „nur Presse"."""
    user, org, role = ctx
    _require_admin(role)
    await _laden(db, org.id, tracker_id)
    await db.execute(delete(PublicTrackerPresse).where(
        PublicTrackerPresse.tracker_id == tracker_id,
        PublicTrackerPresse.telegram_user_id == telegram_user_id,
    ))
    await db.commit()
    await audit.record(
        db, PRESSE_ENTFERNT, request=request, actor_id=user.id, actor_email=user.email,
        org_id=org.id, target_type="aktionsseite", target_id=str(tracker_id),
        detail={"telegram_user_id": telegram_user_id},
    )
    return Response(status_code=204)


# ── Beiträge (Schritt 4) ───────────────────────────────────────────────────
# Übersicht und Notnagel; gearbeitet wird in Telegram. Was hier geschieht,
# zieht die Karte in der Gruppe mit (§ 8.3).

BEITRAG_LIMIT = 200


class BildZeile(BaseModel):
    id: uuid.UUID
    position: int
    width: int
    height: int


class BeitragZeile(BaseModel):
    id: uuid.UUID
    convoy_id: uuid.UUID
    taken_at: datetime
    status: str
    text_public: str | None
    # Intern: was in Telegram stand und wer es geschickt hat.
    text_raw: str | None
    sender_name: str | None
    reviewed_at: datetime | None
    public_since: datetime | None
    photos: list[BildZeile]


class BeitragAenderung(BaseModel):
    aktion: Literal["frei", "ablehnen", "zurueck"] | None = None
    text_public: str | None = Field(default=None, max_length=BEITRAG_TEXT_MAX)


@router.get("/{tracker_id}/beitraege", response_model=list[BeitragZeile])
async def beitraege(
    tracker_id: uuid.UUID,
    status: str | None = None,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    _, org, role = ctx
    _require_admin(role)
    await _laden(db, org.id, tracker_id)
    q = (
        select(PublicTrackerPost)
        .where(PublicTrackerPost.tracker_id == tracker_id)
        .options(selectinload(PublicTrackerPost.photos))
        .order_by(PublicTrackerPost.taken_at.desc())
        .limit(BEITRAG_LIMIT)
    )
    if status:
        if status not in BEITRAG_STATUS:
            raise HTTPException(status_code=422, detail="Unbekannter Status")
        q = q.where(PublicTrackerPost.status == status)
    return (await db.execute(q)).scalars().all()


@router.get("/{tracker_id}/bilder/{photo_id}/{groesse}.webp")
async def bild(
    tracker_id: uuid.UUID,
    photo_id: uuid.UUID,
    groesse: Literal["gross", "klein"],
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Jedes Bild der Seite, auch wartende — nur für Org-Admins."""
    _, org, role = ctx
    _require_admin(role)
    await _laden(db, org.id, tracker_id)
    daten = (await db.execute(
        select(PublicTrackerPhotoData)
        .join(PublicTrackerPhoto, PublicTrackerPhoto.id == PublicTrackerPhotoData.photo_id)
        .join(PublicTrackerPost, PublicTrackerPost.id == PublicTrackerPhoto.post_id)
        .where(PublicTrackerPhoto.id == photo_id, PublicTrackerPost.tracker_id == tracker_id)
    )).scalar_one_or_none()
    if daten is None:
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")
    return Response(
        content=daten.gross if groesse == "gross" else daten.klein,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.put("/{tracker_id}/beitraege/{post_id}", response_model=BeitragZeile)
async def beitrag_aendern(
    tracker_id: uuid.UUID,
    post_id: uuid.UUID,
    data: BeitragAenderung,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Dieselben Übergänge wie die Knöpfe in Telegram (``tg.UEBERGAENGE``)."""
    user, org, role = ctx
    _require_admin(role)
    await _laden(db, org.id, tracker_id)
    post = (await db.execute(
        select(PublicTrackerPost)
        .where(PublicTrackerPost.id == post_id, PublicTrackerPost.tracker_id == tracker_id)
        .options(selectinload(PublicTrackerPost.photos))
    )).scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="Beitrag nicht gefunden")
    jetzt = datetime.now(timezone.utc)
    ereignisse = []
    if "text_public" in data.model_fields_set:
        post.text_public = tg.kuerzen(data.text_public)
        post.text_edited_by_presse = True
        ereignisse.append((tg.AUDIT_TEXT, {}))
    if data.aktion is not None:
        erlaubt, ziel = tg.UEBERGAENGE[data.aktion]
        if post.status not in erlaubt:
            raise HTTPException(status_code=409, detail="Schon erledigt")
        ereignisse.append((tg.AUDIT_BEITRAG[data.aktion], {"von": post.status}))
        post.status = ziel
        post.reviewed_by_user_id = user.id
        post.reviewed_by_telegram_id = None
        post.reviewed_at = jetzt
        if ziel != "freigegeben":
            post.public_since = None
    await db.commit()
    for aktion, detail in ereignisse:
        await audit.record(
            db, aktion, request=request, actor_id=user.id, actor_email=user.email,
            org_id=org.id, target_type="aktionsseite_beitrag", target_id=str(post.id), detail=detail,
        )
    # Die Karte in der Gruppe zieht mit.
    bot = await db.get(PublicTrackerTelegram, org.id)
    if bot is not None and bot.status != "ungueltig":
        await tg.karte_aktualisieren(db, tg.api_fuer(decrypt_secret(bot.bot_token_enc)), post, jetzt)
    # Die öffentliche Antwort liegt bis zu einer Minute im Zwischenspeicher;
    # ein Zurückziehen soll sofort wirken.
    _vergessen((await _laden(db, org.id, tracker_id)).slug)
    return post
