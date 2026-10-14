"""Beiträge aus Telegram: verbinden, annehmen, freigeben.

Plan: docs/superpowers/plans/2026-10-13-fotos-auf-der-aktionsseite.md, § 2, 3, 6.

Fahrer und Begleiter posten Fotos mit ein paar Worten in eine Gruppe (oder ein
Thema), die per Einmalcode an einen Konvoi einer Aktionsseite gebunden ist. Der
Bot antwortet auf jeden Beitrag mit **einer** Nachricht — der Karte — und
bearbeitet sie bei jedem Wechsel, statt neue zu schicken. Freigeben, Text
ändern, Ablehnen und Zurückziehen darf nur, wer per Presse-Code eingetragen ist;
gefragt wird bei jedem Knopfdruck neu, ``callback_data`` wird nichts geglaubt.

Was hinausgeht und wann, entscheidet nicht dieses Modul, sondern
``services/aktionsseite.py`` — die Freigabe kommt zu Verzögerung und
Platzierung dazu, sie ersetzt keine von beiden.

Abgeholt wird per Long Polling (``telegram_schleife``): eine Aufgabe je Bot,
und je Bot nur eine im ganzen Cluster (``pg_try_advisory_lock``), weil Telegram
zwei gleichzeitigen ``getUpdates`` mit 409 antwortet.
"""
import asyncio
import hashlib
import logging
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.models.public_tracker import (
    BEITRAG_TEXT_MAX,
    BILDER_JE_BEITRAG,
    PublicTracker,
    PublicTrackerChat,
    PublicTrackerCode,
    PublicTrackerConvoy,
    PublicTrackerPhoto,
    PublicTrackerPhotoData,
    PublicTrackerPost,
    PublicTrackerPresse,
    PublicTrackerTelegram,
)
from app.services import aktionsseite, aktionsseite_bild, audit, org_module
from app.services.crypto import decrypt_secret
from app.services.telegram import BotInfo, TelegramApi, TelegramFehler

logger = logging.getLogger(__name__)

VERBINDEN_GUELTIG = timedelta(minutes=15)
PRESSE_GUELTIG = timedelta(hours=24)
# Höchstens so viele Bilder je Gruppe und Tag (Plan § 3.1).
BILDER_JE_TAG = 300
# Wie lange eine Aufforderung „Neuer Text …" auf ihre Antwort wartet.
TEXTEINGABE_GUELTIG = timedelta(hours=1)
ZEITZONE = ZoneInfo("Europe/Berlin")

# Für Tests: die Bot-API gestellt (httpx.MockTransport).
transport: httpx.AsyncBaseTransport | None = None

AUDIT_VERBUNDEN = "org.aktionsseite.telegram_verbunden"
AUDIT_PRESSE = "org.aktionsseite.presse_eingetragen"
AUDIT_BEITRAG = {
    "frei": "org.aktionsseite.beitrag_freigegeben",
    "ablehnen": "org.aktionsseite.beitrag_abgelehnt",
    "zurueck": "org.aktionsseite.beitrag_zurueckgezogen",
}
AUDIT_TEXT = "org.aktionsseite.beitrag_text_geaendert"

TEXT_VERBUNDEN = (
    "Verbunden mit „{konvoi}“ auf der Aktionsseite „{seite}“.\n\n"
    "Fotos hier können nach Freigabe durch die Presse öffentlich erscheinen, "
    "mindestens {minuten} Minuten verzögert und nie genauer als die Karte. "
    "Zurückziehen geht über den Knopf am Beitrag, nicht übers Löschen in Telegram."
)
TEXT_CODE_UNBEKANNT = "Der Code ist unbekannt oder abgelaufen. Einen neuen gibt es im Org-Admin."
TEXT_SCHON_ANDERS = "Diese Gruppe (oder dieses Thema) ist schon mit einem anderen Konvoi verbunden."
TEXT_NUR_PRESSE = "Freigeben darf nur die Presse."
TEXT_BILD_FEHLT = "Dieses Bild kann ich nicht übernehmen — bitte als JPEG, PNG oder WebP schicken."
TEXT_HILFE = (
    "Ich nehme Fotos aus den verbundenen Gruppen für die Aktionsseite an.\n\n"
    "Wer freigeben soll, schickt mir hier den Presse-Code: /presse CODE"
)


def api_fuer(token: str) -> TelegramApi:
    return TelegramApi(token, transport=transport)


# ── Kleinteile ohne Datenbank ──────────────────────────────────────────────

_CODE_ZEICHEN = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # ohne 0/O, 1/I


def code_erzeugen() -> str:
    roh = "".join(secrets.choice(_CODE_ZEICHEN) for _ in range(6))
    return f"{roh[:3]}-{roh[3:]}"


def code_hash(code: str) -> str:
    """Groß/klein, Bindestrich und Leerzeichen egal — getippt wird am Handy."""
    sauber = "".join(ch for ch in code.upper() if ch.isalnum())
    return hashlib.sha256(sauber.encode()).hexdigest()


def befehl(text_: str | None, bot_name: str) -> tuple[str, str] | None:
    """``/verbinden@MeinBot 7KQ-2MX`` → ``("verbinden", "7KQ-2MX")``. Ein
    Befehl an einen anderen Bot ist keiner für uns."""
    if not text_ or not text_.startswith("/"):
        return None
    kopf, _, rest = text_.strip().partition(" ")
    name, _, an = kopf[1:].partition("@")
    if an and an.lower() != bot_name.lower():
        return None
    return name.lower(), rest.strip()


def callback(post_id: uuid.UUID, aktion: str) -> str:
    return f"b:{post_id.hex}:{aktion}"


def callback_lesen(daten: str | None) -> tuple[uuid.UUID, str] | None:
    try:
        art, hexid, aktion = (daten or "").split(":")
        return (uuid.UUID(hex=hexid), aktion) if art == "b" else None
    except ValueError:
        return None


def _name(person: dict | None) -> str:
    if not person:
        return "unbekannt"
    teile = [person.get("first_name"), person.get("last_name")]
    return (" ".join(t for t in teile if t) or person.get("username") or "unbekannt")[:255]


def _uhrzeit(t: datetime, bezug: datetime) -> str:
    lokal = t.astimezone(ZEITZONE)
    if lokal.date() == bezug.astimezone(ZEITZONE).date():
        return lokal.strftime("%H:%M")
    return lokal.strftime("%d.%m. %H:%M")


def kuerzen(text_: str | None) -> str | None:
    if not text_ or not text_.strip():
        return None
    text_ = text_.strip()
    return text_ if len(text_) <= BEITRAG_TEXT_MAX else text_[: BEITRAG_TEXT_MAX - 1] + "…"


def karte(
    post: PublicTrackerPost,
    *,
    konvoi: str,
    bilder: int,
    verzoegerung_min: int,
    pruefer: str | None,
    jetzt: datetime,
) -> tuple[str, list[list[dict]]]:
    """Text und Knöpfe der einen Bot-Nachricht je Beitrag."""
    kopf = f"📷 Beitrag · {konvoi} · {bilder} {'Bild' if bilder == 1 else 'Bilder'}"
    if post.sender_name:
        kopf += f" · von {post.sender_name}"
    zeilen = [kopf, f"„{post.text_public}“" if post.text_public else "(ohne Text)"]
    if (
        post.status == "freigegeben"
        and (post.text_raw or None) != (post.text_public or None)
        and post.text_raw
    ):
        zeilen.append(
            f"ℹ️ {post.sender_name or 'Der Absender'} hat den Text in Telegram geändert, "
            "öffentlich bleibt der freigegebene."
        )
    wer = f" von {pruefer}" if pruefer else ""
    if post.status == "wartet":
        zeilen.append("\n⏳ Wartet auf Presse")
        knoepfe = [[
            {"text": "✅ Freigeben", "callback_data": callback(post.id, "frei")},
            {"text": "✏️ Text ändern", "callback_data": callback(post.id, "text")},
            {"text": "❌ Ablehnen", "callback_data": callback(post.id, "ablehnen")},
        ]]
    elif post.status == "freigegeben":
        ab = post.taken_at + timedelta(minutes=max(verzoegerung_min, aktionsseite.MIN_VERZOEGERUNG_MIN))
        if post.not_before and post.not_before > ab:
            ab = post.not_before
        if post.public_since:
            zeilen.append(f"\n🌍 Öffentlich seit {_uhrzeit(post.public_since, jetzt)}")
        else:
            zeilen.append(
                f"\n✅ Freigegeben{wer} · in der Warteschlange\n"
                f"erscheint frühestens {_uhrzeit(ab, jetzt)} "
                f"(Verzögerung {verzoegerung_min} min)"
            )
        knoepfe = [[
            {"text": "✏️ Text ändern", "callback_data": callback(post.id, "text")},
            {"text": "↩️ Zurückziehen", "callback_data": callback(post.id, "zurueck")},
        ]]
    else:
        zeilen.append(f"\n{'❌ Abgelehnt' if post.status == 'abgelehnt' else '↩️ Zurückgezogen'}{wer}")
        knoepfe = [[{"text": "✅ Doch freigeben", "callback_data": callback(post.id, "frei")}]]
    return "\n".join(zeilen), knoepfe


# Was eine Aktion aus welchem Status macht. Alles andere ist „schon erledigt".
UEBERGAENGE: dict[str, tuple[frozenset[str], str]] = {
    "frei": (frozenset({"wartet", "abgelehnt", "zurueckgezogen"}), "freigegeben"),
    "ablehnen": (frozenset({"wartet"}), "abgelehnt"),
    "zurueck": (frozenset({"freigegeben"}), "zurueckgezogen"),
}


# ── Aufforderungen „Neuer Text" ────────────────────────────────────────────
# Im Speicher, wie Belegungen und Passkey-Challenges: Nach einem Neustart
# drückt die Presse eben noch einmal auf „Text ändern".

_texteingaben: dict[tuple[int, int], tuple[uuid.UUID, int, float]] = {}


def _eingabe_merken(chat_id: int, prompt_id: int, post_id: uuid.UUID, user_id: int) -> None:
    jetzt = time.monotonic()
    for k in [k for k, (_, _, bis) in _texteingaben.items() if bis < jetzt]:
        del _texteingaben[k]
    _texteingaben[(chat_id, prompt_id)] = (post_id, user_id, jetzt + TEXTEINGABE_GUELTIG.total_seconds())


def vergessen() -> None:
    _texteingaben.clear()


# ── Verarbeitung eines Updates ─────────────────────────────────────────────


class _Lauf:
    """Was eine Verarbeitung braucht: Sitzung, Bot, Draht, Uhr."""

    def __init__(self, db: AsyncSession, bot: PublicTrackerTelegram, ich: BotInfo, api: TelegramApi,
                 jetzt: datetime):
        self.db, self.bot, self.ich, self.api, self.jetzt = db, bot, ich, api, jetzt

    async def antworten(self, nachricht: dict, text_: str) -> None:
        await self.api.senden(
            nachricht["chat"]["id"], text_,
            thread_id=_thema(nachricht), antwort_auf=nachricht.get("message_id"),
        )


def _thema(nachricht: dict) -> int | None:
    return nachricht.get("message_thread_id") if nachricht.get("is_topic_message") else None


async def verarbeiten(
    db: AsyncSession,
    bot: PublicTrackerTelegram,
    ich: BotInfo,
    api: TelegramApi,
    update: dict,
    jetzt: datetime | None = None,
) -> None:
    """Ein Update von Telegram. Fehler eines Updates halten die übrigen nicht auf;
    das fängt der Aufrufer."""
    lauf = _Lauf(db, bot, ich, api, jetzt or datetime.now(timezone.utc))
    if cq := update.get("callback_query"):
        await _knopf(lauf, cq)
    elif nachricht := update.get("message"):
        if (nachricht.get("from") or {}).get("is_bot"):
            return
        if nachricht.get("chat", {}).get("type") == "private":
            await _privat(lauf, nachricht)
        else:
            await _gruppe(lauf, nachricht)
    elif bearbeitet := update.get("edited_message"):
        await _bearbeitet(lauf, bearbeitet)


async def _privat(lauf: _Lauf, nachricht: dict) -> None:
    b = befehl(nachricht.get("text"), lauf.ich.username)
    if b is None:
        return
    name, arg = b
    if name != "presse":
        await lauf.antworten(nachricht, TEXT_HILFE)
        return
    code = await _code(lauf, arg, "presse")
    if code is None:
        await lauf.antworten(nachricht, TEXT_CODE_UNBEKANNT)
        return
    von = nachricht["from"]
    eintrag = await lauf.db.get(PublicTrackerPresse, (code.tracker_id, von["id"]))
    if eintrag is None:
        eintrag = PublicTrackerPresse(tracker_id=code.tracker_id, telegram_user_id=von["id"])
        lauf.db.add(eintrag)
    eintrag.display_name = _name(von)
    eintrag.username = (von.get("username") or None)
    seite = await lauf.db.get(PublicTracker, code.tracker_id)
    await lauf.db.commit()
    await audit.record(
        lauf.db, AUDIT_PRESSE, org_id=lauf.bot.organization_id,
        target_type="aktionsseite", target_id=str(code.tracker_id),
        detail={"telegram_user_id": von["id"], "name": eintrag.display_name},
    )
    await lauf.antworten(
        nachricht,
        f"Du gibst jetzt Beiträge für „{seite.title}“ frei. "
        "Die Knöpfe an den Beiträgen in den Gruppen gelten ab sofort für dich.",
    )


async def _code(lauf: _Lauf, roh: str, art: str) -> PublicTrackerCode | None:
    """Ein gültiger Code dieser Art, an einer Seite der Organisation dieses Bots."""
    if not roh:
        return None
    code = await lauf.db.get(PublicTrackerCode, code_hash(roh))
    if code is None or code.art != art or code.expires_at <= lauf.jetzt:
        return None
    seite = await lauf.db.get(PublicTracker, code.tracker_id)
    if seite is None or seite.organization_id != lauf.bot.organization_id:
        return None
    return code


async def _bindung(lauf: _Lauf, chat_id: int, thema: int | None):
    """Gruppe/Thema → (Bindung, Seite), nur für Seiten der Organisation des Bots."""
    q = select(PublicTrackerChat).where(PublicTrackerChat.chat_id == chat_id)
    q = q.where(
        PublicTrackerChat.thread_id.is_(None) if thema is None else PublicTrackerChat.thread_id == thema
    )
    chat = (await lauf.db.execute(q)).scalar_one_or_none()
    if chat is None:
        return None, None
    seite = await lauf.db.get(PublicTracker, chat.tracker_id)
    if seite is None or seite.organization_id != lauf.bot.organization_id:
        return None, None
    return chat, seite


async def _gruppe(lauf: _Lauf, nachricht: dict) -> None:
    b = befehl(nachricht.get("text"), lauf.ich.username)
    if b is not None and b[0] == "verbinden":
        await _verbinden(lauf, nachricht, b[1])
        return
    antwort_auf = nachricht.get("reply_to_message") or {}
    if nachricht.get("text") and (nachricht["chat"]["id"], antwort_auf.get("message_id")) in _texteingaben:
        await _neuer_text(lauf, nachricht)
        return
    if nachricht.get("photo") or (nachricht.get("document") or {}).get("mime_type", "").startswith("image/"):
        await _beitrag(lauf, nachricht)


async def _verbinden(lauf: _Lauf, nachricht: dict, arg: str) -> None:
    code = await _code(lauf, arg, "verbinden")
    if code is None:
        await lauf.antworten(nachricht, TEXT_CODE_UNBEKANNT)
        return
    chat_id, thema = nachricht["chat"]["id"], _thema(nachricht)
    vorhanden, _ = await _bindung(lauf, chat_id, thema)
    if vorhanden is not None and (vorhanden.tracker_id, vorhanden.convoy_id) != (code.tracker_id, code.convoy_id):
        await lauf.antworten(nachricht, TEXT_SCHON_ANDERS)
        return
    if vorhanden is None:
        # Ein neuer Code ersetzt die bisherige Gruppe des Konvois.
        alt = (await lauf.db.execute(
            select(PublicTrackerChat).where(
                PublicTrackerChat.tracker_id == code.tracker_id,
                PublicTrackerChat.convoy_id == code.convoy_id,
            )
        )).scalar_one_or_none()
        if alt is not None:
            await lauf.db.delete(alt)
            await lauf.db.flush()
        lauf.db.add(PublicTrackerChat(
            tracker_id=code.tracker_id, convoy_id=code.convoy_id, chat_id=chat_id,
            thread_id=thema, chat_title=(nachricht["chat"].get("title") or "")[:255] or None,
        ))
    seite = await lauf.db.get(PublicTracker, code.tracker_id)
    konvoi = await lauf.db.get(PublicTrackerConvoy, (code.tracker_id, code.convoy_id))
    await lauf.db.delete(code)  # einmalig
    try:
        await lauf.db.commit()
    except IntegrityError:
        await lauf.db.rollback()
        await lauf.antworten(nachricht, TEXT_SCHON_ANDERS)
        return
    await audit.record(
        lauf.db, AUDIT_VERBUNDEN, org_id=lauf.bot.organization_id,
        target_type="aktionsseite", target_id=str(seite.id),
        detail={"convoy_id": str(konvoi.convoy_id), "chat_id": chat_id, "thread_id": thema,
                "telegram_user_id": (nachricht.get("from") or {}).get("id")},
    )
    await lauf.antworten(nachricht, TEXT_VERBUNDEN.format(
        konvoi=konvoi.display_name, seite=seite.title,
        minuten=max(seite.delay_minutes, aktionsseite.MIN_VERZOEGERUNG_MIN),
    ))


async def _seite_offen(lauf: _Lauf, seite: PublicTracker) -> bool:
    return aktionsseite.ist_aktiv(seite, lauf.jetzt) and await org_module.freigegeben(
        lauf.db, seite.organization_id, org_module.AKTIONSSEITEN
    )


async def _beitrag(lauf: _Lauf, nachricht: dict) -> None:
    chat_id = nachricht["chat"]["id"]
    chat, seite = await _bindung(lauf, chat_id, _thema(nachricht))
    if chat is None or not await _seite_offen(lauf, seite):
        return
    # Weitergeleitetes kann alt sein oder von woanders — Zeit und Ort passen nicht.
    if nachricht.get("forward_origin") or nachricht.get("forward_date"):
        return
    gruppe_id = nachricht.get("media_group_id")
    post = None
    if gruppe_id:
        post = (await lauf.db.execute(
            select(PublicTrackerPost)
            .where(PublicTrackerPost.chat_id == chat_id, PublicTrackerPost.media_group_id == gruppe_id)
            .options(selectinload(PublicTrackerPost.photos))
        )).scalar_one_or_none()
        if post is not None and post.tracker_id != chat.tracker_id:
            return
    if post is not None and len(post.photos) >= BILDER_JE_BEITRAG:
        return
    if await _bilder_heute(lauf, chat_id) >= BILDER_JE_TAG:
        logger.info("Telegram: Tagesgrenze für Chat %s erreicht", chat_id)
        return

    datei = nachricht["photo"][-1] if nachricht.get("photo") else nachricht["document"]
    try:
        bild = aktionsseite_bild.verarbeiten(await lauf.api.datei(datei["file_id"]))
    except (aktionsseite_bild.BildFehler, TelegramFehler) as e:
        logger.info("Telegram: Bild nicht übernommen (%s)", e)
        await lauf.antworten(nachricht, TEXT_BILD_FEHLT)
        return

    unterschrift = nachricht.get("caption")
    neu = post is None
    if neu:
        von = nachricht.get("from") or {}
        post = PublicTrackerPost(
            public_id=secrets.token_urlsafe(16), tracker_id=chat.tracker_id, convoy_id=chat.convoy_id,
            quelle="telegram", chat_id=chat_id, message_id=nachricht["message_id"],
            media_group_id=gruppe_id,
            # message.date, nicht EXIF: das stellt jedes Handy anders und lässt
            # sich frei setzen.
            taken_at=datetime.fromtimestamp(nachricht["date"], timezone.utc),
            status="wartet", text_raw=unterschrift, text_public=kuerzen(unterschrift),
            sender_telegram_id=von.get("id"), sender_name=_name(von),
            photos=[],
        )
        lauf.db.add(post)
    elif unterschrift and not post.text_raw:
        # Im Album trägt nur eine Nachricht die Unterschrift, nicht unbedingt die erste.
        post.text_raw = unterschrift
        if post.status == "wartet" and not post.text_edited_by_presse:
            post.text_public = kuerzen(unterschrift)
    foto = PublicTrackerPhoto(
        public_id=secrets.token_urlsafe(16), position=len(post.photos),
        width=bild.breite, height=bild.hoehe,
    )
    post.photos.append(foto)
    await lauf.db.flush()
    lauf.db.add(PublicTrackerPhotoData(photo_id=foto.id, gross=bild.gross, klein=bild.klein))
    try:
        await lauf.db.commit()
    except IntegrityError:
        # Dieselbe Nachricht zum zweiten Mal.
        await lauf.db.rollback()
        return
    if neu:
        text_, knoepfe = await _karte(lauf, post)
        gesendet = await lauf.api.senden(
            chat_id, text_, thread_id=_thema(nachricht), antwort_auf=nachricht["message_id"],
            knoepfe=knoepfe,
        )
        post.card_message_id = gesendet["message_id"]
        await lauf.db.commit()
    else:
        await karte_aktualisieren(lauf.db, lauf.api, post, lauf.jetzt)


async def _bilder_heute(lauf: _Lauf, chat_id: int) -> int:
    return (await lauf.db.execute(
        select(func.count()).select_from(PublicTrackerPhoto).join(PublicTrackerPost).where(
            PublicTrackerPost.chat_id == chat_id,
            PublicTrackerPost.created_at > lauf.jetzt - timedelta(days=1),
        )
    )).scalar_one()


async def _karte(lauf_or_db, post: PublicTrackerPost, jetzt: datetime | None = None):
    db = lauf_or_db.db if isinstance(lauf_or_db, _Lauf) else lauf_or_db
    jetzt = jetzt or (lauf_or_db.jetzt if isinstance(lauf_or_db, _Lauf) else datetime.now(timezone.utc))
    seite = await db.get(PublicTracker, post.tracker_id)
    konvoi = await db.get(PublicTrackerConvoy, (post.tracker_id, post.convoy_id))
    pruefer = None
    if post.reviewed_by_telegram_id is not None:
        p = await db.get(PublicTrackerPresse, (post.tracker_id, post.reviewed_by_telegram_id))
        pruefer = p.display_name if p else None
    elif post.reviewed_by_user_id is not None:
        pruefer = "ConvoyPlan"
    bilder = (await db.execute(
        select(func.count()).select_from(PublicTrackerPhoto).where(PublicTrackerPhoto.post_id == post.id)
    )).scalar_one()
    return karte(
        post, konvoi=konvoi.display_name if konvoi else "?", bilder=bilder,
        verzoegerung_min=seite.delay_minutes, pruefer=pruefer, jetzt=jetzt,
    )


async def karte_aktualisieren(
    db: AsyncSession, api: TelegramApi, post: PublicTrackerPost, jetzt: datetime | None = None
) -> None:
    """Die Karte in der Gruppe auf den Stand bringen — auch nach einer
    Änderung im Org-Admin (§ 8.3)."""
    if post.chat_id is None or post.card_message_id is None:
        return
    text_, knoepfe = await _karte(db, post, jetzt)
    try:
        await api.bearbeiten(post.chat_id, post.card_message_id, text_, knoepfe)
    except TelegramFehler as e:
        logger.info("Telegram: Karte nicht bearbeitet (%s)", e.beschreibung)


async def _knopf(lauf: _Lauf, cq: dict) -> None:
    gelesen = callback_lesen(cq.get("data"))
    nachricht = cq.get("message") or {}
    post = await lauf.db.get(PublicTrackerPost, gelesen[0]) if gelesen else None
    if post is None or post.chat_id != (nachricht.get("chat") or {}).get("id"):
        await lauf.api.quittieren(cq["id"], "Diesen Beitrag gibt es nicht mehr.")
        return
    seite = await lauf.db.get(PublicTracker, post.tracker_id)
    if seite is None or seite.organization_id != lauf.bot.organization_id:
        await lauf.api.quittieren(cq["id"], "Diesen Beitrag gibt es nicht mehr.")
        return
    von = cq.get("from") or {}
    # Die Presse dieser Seite — eine Presse-Zusage für eine andere Seite zählt nicht.
    presse = await lauf.db.get(PublicTrackerPresse, (post.tracker_id, von.get("id")))
    if presse is None:
        await lauf.api.quittieren(cq["id"], TEXT_NUR_PRESSE, alarm=True)
        return
    aktion = gelesen[1]

    if aktion == "text":
        if post.status not in ("wartet", "freigegeben"):
            await lauf.api.quittieren(cq["id"], "Schon erledigt.")
            return
        frage = await lauf.api.senden(
            post.chat_id,
            f"✏️ {presse.display_name}: neuer Text für diesen Beitrag — antworte auf diese Nachricht "
            f"(höchstens {BEITRAG_TEXT_MAX} Zeichen, „-“ für ohne Text).",
            thread_id=nachricht.get("message_thread_id") if nachricht.get("is_topic_message") else None,
            antwort_auf=post.card_message_id, erzwinge_antwort=True,
        )
        _eingabe_merken(post.chat_id, frage["message_id"], post.id, von["id"])
        await lauf.api.quittieren(cq["id"])
        return

    uebergang = UEBERGAENGE.get(aktion)
    if uebergang is None or post.status not in uebergang[0]:
        await lauf.api.quittieren(cq["id"], "Schon erledigt.")
        await karte_aktualisieren(lauf.db, lauf.api, post, lauf.jetzt)
        return
    vorher = post.status
    post.status = uebergang[1]
    post.reviewed_by_telegram_id = von["id"]
    post.reviewed_by_user_id = None
    post.reviewed_at = lauf.jetzt
    if post.status != "freigegeben":
        post.public_since = None
    await lauf.db.commit()
    await audit.record(
        lauf.db, AUDIT_BEITRAG[aktion], org_id=seite.organization_id,
        target_type="aktionsseite_beitrag", target_id=str(post.id),
        detail={"von": vorher, "telegram_user_id": von["id"], "name": presse.display_name},
    )
    await lauf.api.quittieren(cq["id"], {
        "frei": "Freigegeben — erscheint nach der Verzögerung.",
        "ablehnen": "Abgelehnt.",
        "zurueck": "Zurückgezogen.",
    }[aktion])
    await karte_aktualisieren(lauf.db, lauf.api, post, lauf.jetzt)


async def _neuer_text(lauf: _Lauf, nachricht: dict) -> None:
    schluessel = (nachricht["chat"]["id"], nachricht["reply_to_message"]["message_id"])
    post_id, wer, _ = _texteingaben[schluessel]
    von = nachricht.get("from") or {}
    if von.get("id") != wer:
        return  # Nur die Antwort dessen, der gedrückt hat.
    post = await lauf.db.get(PublicTrackerPost, post_id)
    if post is None:
        _texteingaben.pop(schluessel, None)
        return
    # Hat die Presse noch Zugang? Entfernen wirkt sofort.
    if await lauf.db.get(PublicTrackerPresse, (post.tracker_id, wer)) is None:
        _texteingaben.pop(schluessel, None)
        return
    roh = nachricht["text"].strip()
    if len(roh) > BEITRAG_TEXT_MAX:
        await lauf.antworten(nachricht, f"Zu lang — höchstens {BEITRAG_TEXT_MAX} Zeichen.")
        return
    post.text_public = None if roh in ("", "-") else roh
    post.text_edited_by_presse = True
    await lauf.db.commit()
    _texteingaben.pop(schluessel, None)
    await audit.record(
        lauf.db, AUDIT_TEXT, org_id=lauf.bot.organization_id,
        target_type="aktionsseite_beitrag", target_id=str(post.id),
        detail={"telegram_user_id": wer},
    )
    await karte_aktualisieren(lauf.db, lauf.api, post, lauf.jetzt)


async def _bearbeitet(lauf: _Lauf, nachricht: dict) -> None:
    """Ein Fahrer bearbeitet seine Unterschrift. Vor der Freigabe ersetzt das den
    Vorschlag, danach nie — sonst ließe sich ein freigegebener Text still austauschen."""
    chat_id = nachricht["chat"]["id"]
    post = (await lauf.db.execute(
        select(PublicTrackerPost).where(
            PublicTrackerPost.chat_id == chat_id,
            PublicTrackerPost.message_id == nachricht.get("message_id"),
        )
    )).scalar_one_or_none()
    if post is None and nachricht.get("media_group_id"):
        post = (await lauf.db.execute(
            select(PublicTrackerPost).where(
                PublicTrackerPost.chat_id == chat_id,
                PublicTrackerPost.media_group_id == nachricht["media_group_id"],
            )
        )).scalar_one_or_none()
    if post is None or "caption" not in nachricht and "text" not in nachricht:
        return
    unterschrift = nachricht.get("caption")
    post.text_raw = unterschrift
    if post.status == "wartet" and not post.text_edited_by_presse:
        post.text_public = kuerzen(unterschrift)
    await lauf.db.commit()
    await karte_aktualisieren(lauf.db, lauf.api, post, lauf.jetzt)


# ── Abholen ────────────────────────────────────────────────────────────────


async def einmal_abholen(org_id: uuid.UUID, warten: int = 25, pause_bei_fehler: float = 10.0) -> bool:
    """Ein Durchgang ``getUpdates`` für den Bot einer Organisation.

    ``False``, wenn es (nicht mehr) zu tun gibt: kein Bot, Modul gesperrt,
    Token ungültig. Den Status schreibt der Durchgang in die Bot-Zeile."""
    async with AsyncSessionLocal() as db:
        bot = await db.get(PublicTrackerTelegram, org_id)
        if bot is None or bot.status == "ungueltig":
            return False
        if not await org_module.freigegeben(db, org_id, org_module.AKTIONSSEITEN):
            return False
        api = api_fuer(decrypt_secret(bot.bot_token_enc))
        try:
            ich = await api.ich()
            updates = await api.updates(bot.update_offset, warten)
        except TelegramFehler as e:
            await _fehler_merken(db, bot, e)
            if e.code in (401, 404):
                return False
            # Sonst fragte die Schleife ohne Pause gleich wieder — ein Fehler
            # kommt sofort zurück, nicht nach den 25 s des Long Pollings.
            await asyncio.sleep(min(e.warten, 300) if e.warten else pause_bei_fehler)
            return True
        bot.status = "bereit" if ich.liest_alles else "privat"
        bot.bot_username = ich.username
        bot.last_error = None
        bot.checked_at = datetime.now(timezone.utc)
        await db.commit()
        for u in updates:
            try:
                await verarbeiten(db, bot, ich, api, u)
            except Exception:
                # Ein kaputtes Update darf die Gruppe nicht blockieren: weiter.
                logger.exception("Telegram: Update %s nicht verarbeitet", u.get("update_id"))
                await db.rollback()
            bot = await db.get(PublicTrackerTelegram, org_id)
            if bot is None:
                return False
            bot.update_offset = max(bot.update_offset, u["update_id"] + 1)
            await db.commit()
    return True


async def _fehler_merken(db: AsyncSession, bot: PublicTrackerTelegram, e: TelegramFehler) -> None:
    bot.status = {401: "ungueltig", 404: "ungueltig", 409: "konflikt"}.get(e.code, "fehler")
    bot.last_error = e.beschreibung
    bot.checked_at = datetime.now(timezone.utc)
    await db.commit()
    logger.warning("Telegram-Bot der Organisation %s: %s", bot.organization_id, e.beschreibung)


def _sperrschluessel(org_id: uuid.UUID) -> int:
    return int.from_bytes(hashlib.sha256(b"telegram:" + org_id.bytes).digest()[:8], "big", signed=True)


async def _bot_laufen(org_id: uuid.UUID) -> None:
    """Holt für einen Bot ab, solange es ihn gibt — und nur, wenn kein anderer
    Prozess es schon tut."""
    async with engine.connect() as conn:
        if not await conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": _sperrschluessel(org_id)}):
            return
        try:
            pause = 1.0
            while True:
                try:
                    weiter = await einmal_abholen(org_id)
                    pause = 1.0
                except Exception:
                    logger.exception("Telegram: Abholen für %s gescheitert", org_id)
                    weiter = True
                    pause = min(pause * 2, 60.0)
                    await asyncio.sleep(pause)
                if not weiter:
                    return
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _sperrschluessel(org_id)})


async def telegram_schleife(intervall: float = 30.0) -> None:
    """Startet je eingetragenem Bot eine Abholaufgabe und räumt beendete weg.

    Eine Aufgabe, die endet (Token ungültig, Modul gesperrt, Bot entfernt), wird
    beim nächsten Durchgang neu gestartet, falls es den Bot noch gibt — ein
    neuer Token setzt den Status zurück."""
    laufend: dict[uuid.UUID, asyncio.Task] = {}
    try:
        while True:
            if settings.telegram_enabled:
                try:
                    async with AsyncSessionLocal() as db:
                        orgs = set((await db.execute(
                            select(PublicTrackerTelegram.organization_id).where(
                                PublicTrackerTelegram.status != "ungueltig"
                            )
                        )).scalars().all())
                    for org_id, task in list(laufend.items()):
                        if task.done() or org_id not in orgs:
                            task.cancel()
                            del laufend[org_id]
                    for org_id in orgs - laufend.keys():
                        laufend[org_id] = asyncio.create_task(_bot_laufen(org_id))
                except Exception:
                    logger.exception("Telegram-Schleife: Durchgang gescheitert")
            await asyncio.sleep(intervall)
    finally:
        for task in laufend.values():
            task.cancel()
