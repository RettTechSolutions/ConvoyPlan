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
import re
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
    PublicTrackerVideo,
)
from app.models.user import User
from app.services import (
    aktionsseite,
    aktionsseite_bild,
    aktionsseite_gruppe,
    aktionsseite_link,
    aktionsseite_video,
    aktionsseite_vorschau,
    audit,
    org_module,
)
from app.services.crypto import decrypt_secret
from app.services.telegram import BotInfo, TelegramApi, TelegramFehler

logger = logging.getLogger(__name__)

VERBINDEN_GUELTIG = timedelta(minutes=15)
PRESSE_GUELTIG = timedelta(hours=24)
# Höchstens so viele Bilder je Gruppe und Tag (Plan § 3.1).
BILDER_JE_TAG = 300
# Und so viele Link-Beiträge (§ 11).
LINKS_JE_TAG = 100
# Und so viele Videos (§ 15) — jedes kostet den Medien-Container eine Minute CPU.
VIDEOS_JE_TAG = 50
# Dieselbe Ansage in derselben Gruppe höchstens so oft (Seite zu, Tagesgrenze).
ANSAGE_WIEDER = timedelta(hours=24)
# Videodateien ohne Beitrag (Retention, Konvoi aus der Seite) so oft wegräumen.
AUFRAEUMEN_ALLE = 3600.0
# Höchstens so viele gedrosselte Karten je Durchgang nachholen.
KARTEN_JE_DURCHGANG = 20
# Wie lange eine Aufforderung „Neuer Text …" auf ihre Antwort wartet.
TEXTEINGABE_GUELTIG = timedelta(hours=1)
ZEITZONE = ZoneInfo("Europe/Berlin")
# Wie weit die Presse mit ``/ab`` in die Zukunft terminieren darf (§ 3.5).
TERMIN_MAX = timedelta(days=7)

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
AUDIT_TERMIN = "org.aktionsseite.beitrag_terminiert"

TEXT_VERBUNDEN = (
    "Verbunden mit „{konvoi}“ auf der Aktionsseite „{seite}“.\n\n"
    "Fotos und Videos (bis 60 Sekunden, mit Ton) hier können nach Freigabe durch die Presse "
    "öffentlich erscheinen, mindestens {minuten} Minuten verzögert und nie genauer als die Karte. "
    "Links zu Instagram, YouTube, Facebook oder TikTok auch, als Link — "
    "als Antwort auf ein Foto gehören sie zu dessen Zeit und Ort. "
    "Zurückziehen geht über den Knopf am Beitrag, nicht übers Löschen in Telegram."
)
TEXT_CODE_UNBEKANNT = "Der Code ist unbekannt oder abgelaufen. Einen neuen gibt es im Org-Admin."
TEXT_SCHON_ANDERS = "Diese Gruppe (oder dieses Thema) ist schon mit einem anderen Konvoi verbunden."
TEXT_NUR_PRESSE = "Freigeben darf nur die Presse."
TEXT_BILD_FEHLT = "Dieses Bild kann ich nicht übernehmen — bitte als JPEG, PNG oder WebP schicken."
TEXT_VIDEO_ZU_LANG = (
    f"Dieses Video ist länger als {aktionsseite_video.MAX_SEKUNDEN} Sekunden — "
    "bitte kürzen und noch einmal schicken."
)
TEXT_VIDEO_ZU_GROSS = (
    "Dieses Video ist größer als 20 MB, und Telegram hat keine kleinere Fassung davon — so groß "
    "gibt es mir Telegram nicht. Bitte als Video statt als Datei schicken, kürzer oder in "
    "geringerer Qualität."
)
TEXT_VIDEO_AUS = "Videos kann ich hier nicht annehmen, nur Fotos."
TEXT_VIDEO_FEHLT = "Dieses Video konnte ich gerade nicht holen — bitte noch einmal schicken."
TEXT_SEITE_ZU = (
    "Die Aktionsseite „{seite}“ ist gerade nicht aktiv. Fotos, Videos und Links von hier nehme ich "
    "nicht an — sie erscheinen nicht und werden nicht gespeichert."
)
TEXT_TAGESGRENZE = (
    "Für den Moment nehme ich aus dieser Gruppe keine weiteren {was} an "
    "(höchstens {n} in 24 Stunden). Später geht es weiter."
)
TEXT_AB_HILFE = (
    "So geht's: als Antwort auf die Karte eines Beitrags /ab 18:00 oder /ab 27.12. 18:00 — "
    "/ab - nimmt den Termin wieder weg. Früher als die Verzögerung geht nie."
)
TEXT_HALLO = (
    "Hallo! Ich bringe Fotos, Videos und Links aus dieser Gruppe auf eine Aktionsseite.\n\n"
    "Verbinden: /verbinden CODE — den Code gibt es im Org-Admin am Konvoi der Seite. "
    "Am besten macht ihr mich hier zum Admin ({rechte}), dann richte ich Beschreibung, "
    "Gruppenbild und eine angeheftete Anleitung selbst ein."
)
TEXT_HALLO_PRIVAT = (
    "\n\nNoch sehe ich in Gruppen keine Fotos: Bei @BotFather /setprivacy → Disable, "
    "danach mich einmal entfernen und neu hinzufügen — oder mich zum Admin machen."
)
TEXT_WILLKOMMEN = (
    "Willkommen, {namen}! Fotos, Videos und Links, die ihr hier postet, können nach Freigabe durch "
    "die Presse auf der Aktionsseite „{seite}“ erscheinen — mindestens {minuten} Minuten "
    "verzögert und nie genauer als die Karte. Wer das nicht möchte, postet hier keine Fotos."
)
# Höchstens eine Begrüßung je Gruppe und Minute; die vorige löscht der Bot.
WILLKOMMEN_PAUSE = timedelta(minutes=1)
TEXT_HILFE = (
    "Ich nehme Fotos, Videos und Links aus den verbundenen Gruppen für die Aktionsseite an.\n\n"
    "Wer freigeben soll, schickt mir hier den Presse-Code: /presse CODE"
)


# Was Telegram beim Tippen von „/“ anbietet. Getrennt nach Ort, weil jeder
# Befehl nur an einem gilt: ``/presse`` privat, die übrigen in der Gruppe.
BEFEHLE: dict[str, list[tuple[str, str]]] = {
    "all_private_chats": [
        ("presse", "Als Presse eintragen: /presse CODE (Code aus dem Org-Admin)"),
    ],
    "all_group_chats": [
        ("verbinden", "Gruppe oder Thema mit einem Konvoi verbinden: /verbinden CODE"),
        ("ab", "Nur Presse, als Antwort auf einen Beitrag: /ab 18:00 zeigt ihn erst dann"),
    ],
}


async def befehle_eintragen(api: TelegramApi) -> bool:
    """Legt die Befehle im Bot ab. Scheitert das, bleibt der Bot trotzdem
    nutzbar — die Befehle gehen auch getippt; deshalb nur ein Eintrag im Log."""
    try:
        for bereich, befehle in BEFEHLE.items():
            await api.befehle_setzen(befehle, bereich)
    except TelegramFehler as e:
        logger.info("Telegram: Befehle nicht eingetragen (%s)", e.beschreibung)
        return False
    return True


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


class TerminFehler(ValueError):
    pass


_TERMIN = re.compile(r"^(?:(\d{1,2})\.(\d{1,2})\.(\d{4})?\s+)?(\d{1,2})[:.](\d{2})(?:\s*uhr)?$", re.IGNORECASE)


def termin_lesen(arg: str, jetzt: datetime) -> datetime | None:
    """``/ab``-Zeit in deutscher Ortszeit. ``18:00`` ist das nächste 18:00
    (um 23 Uhr also morgen früh), ``27.12. 18:00`` ein Tag im kommenden Jahr,
    wenn er dieses schon vorbei ist; ``-`` nimmt den Termin weg (``None``).
    Höchstens ``TERMIN_MAX`` voraus."""
    arg = arg.strip()
    if arg in ("-", "weg", "aus"):
        return None
    m = _TERMIN.match(arg)
    if not m:
        raise TerminFehler(arg)
    tag, monat, jahr, stunde, minute = m.groups()
    lokal_jetzt = jetzt.astimezone(ZEITZONE)
    try:
        if tag:
            j = int(jahr) if jahr else lokal_jetzt.year
            t = datetime(j, int(monat), int(tag), int(stunde), int(minute), tzinfo=ZEITZONE)
            if not jahr and t < lokal_jetzt - timedelta(days=1):
                t = t.replace(year=j + 1)
        else:
            t = lokal_jetzt.replace(hour=int(stunde), minute=int(minute), second=0, microsecond=0)
            if t <= lokal_jetzt:
                t += timedelta(days=1)
    except ValueError as e:
        raise TerminFehler(arg) from e
    t = t.astimezone(timezone.utc)
    if t > jetzt + TERMIN_MAX:
        raise TerminFehler(arg)
    return t


def regelzeit(post: PublicTrackerPost, verzoegerung_min: int) -> datetime:
    """Frühestens dann darf ein Beitrag nach der Verzögerung hinaus. Halte
    können ihn länger zurückhalten — das weiß erst ``beitrag_sichtbar``."""
    return post.taken_at + timedelta(minutes=max(verzoegerung_min, aktionsseite.MIN_VERZOEGERUNG_MIN))


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


def _absender(seite: PublicTracker, von: dict) -> str | None:
    """Der Name für die Karte — nur, wenn die Seite ihn zeigen soll (§ 14.4)."""
    return _name(von) if seite.show_sender else None


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
    video: PublicTrackerVideo | None = None,
) -> tuple[str, list[list[dict]]]:
    """Text und Knöpfe der einen Bot-Nachricht je Beitrag."""
    if post.link_url:
        kopf = f"🔗 Link · {konvoi} · {aktionsseite_link.NAMEN.get(post.link_dienst, post.link_dienst)}"
    elif video is not None:
        sek = round(video.seconds)
        kopf = f"🎬 Video · {konvoi} · {sek // 60}:{sek % 60:02d}"
    else:
        kopf = f"📷 Beitrag · {konvoi} · {bilder} {'Bild' if bilder == 1 else 'Bilder'}"
    if post.sender_name:
        kopf += f" · von {post.sender_name}"
    zeilen = [kopf, f"„{post.text_public}“" if post.text_public else "(ohne Text)"]
    if post.link_url:
        # Die Presse soll sehen, wohin der Link führt — bereinigt, wie er hinausgeht.
        zeilen.append(post.link_url)
        # Und ob ein Bild des Dienstes mit hinausgeht (§ 11.2).
        zeilen.append("🖼 mit Vorschaubild des Dienstes" if bilder else "ohne Vorschaubild")
    if video is not None:
        # Der Ton geht mit hinaus (§ 15): Durchsagen und Gespräche verraten,
        # was das Bild nicht zeigt.
        zeilen.append("🔊 mit Ton — vor dem Freigeben anhören" if video.sound else "🔇 ohne Ton")
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
    termin = post.not_before and post.not_before > regelzeit(post, verzoegerung_min)
    if post.status == "wartet":
        zeilen.append("\n⏳ Wartet auf Presse")
        if termin:
            zeilen.append(f"⏰ Termin: frühestens {_uhrzeit(post.not_before, jetzt)}")
        knoepfe = [[
            {"text": "✅ Freigeben", "callback_data": callback(post.id, "frei")},
            {"text": "✏️ Text ändern", "callback_data": callback(post.id, "text")},
            {"text": "❌ Ablehnen", "callback_data": callback(post.id, "ablehnen")},
        ]]
    elif post.status == "freigegeben":
        ab = post.not_before if termin else regelzeit(post, verzoegerung_min)
        if post.public_since:
            zeilen.append(f"\n🌍 Öffentlich seit {_uhrzeit(post.public_since, jetzt)}")
        else:
            grund = "Termin der Presse" if termin else f"Verzögerung {verzoegerung_min} min"
            zeilen.append(
                f"\n✅ Freigegeben{wer} · in der Warteschlange\n"
                f"erscheint frühestens {_uhrzeit(ab, jetzt)} ({grund})"
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


# Gruppe → (Zeitpunkt, Nachricht) der letzten Begrüßung. Im Speicher: Nach
# einem Neustart käme höchstens eine Begrüßung zu viel.
_willkommen: dict[int, tuple[float, int]] = {}


def vergessen() -> None:
    _texteingaben.clear()
    _willkommen.clear()


# ── Verarbeitung eines Updates ─────────────────────────────────────────────


class _Lauf:
    """Was eine Verarbeitung braucht: Sitzung, Bot, Draht, Uhr."""

    def __init__(self, db: AsyncSession, bot: PublicTrackerTelegram, ich: BotInfo, api: TelegramApi,
                 jetzt: datetime):
        self.db, self.bot, self.ich, self.api, self.jetzt = db, bot, ich, api, jetzt

    async def antworten(self, nachricht: dict, text_: str) -> dict:
        return await self.api.senden(
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
    elif mitglied := update.get("my_chat_member"):
        await _ich_in_gruppe(lauf, mitglied)


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
    if neu := nachricht.get("new_chat_members"):
        await _begruessen(lauf, nachricht, [m for m in neu if not m.get("is_bot")])
        return
    b = befehl(nachricht.get("text"), lauf.ich.username)
    if b is not None and b[0] == "verbinden":
        await _verbinden(lauf, nachricht, b[1])
        return
    if b is not None and b[0] == "ab":
        await _ab(lauf, nachricht, b[1])
        return
    antwort_auf = nachricht.get("reply_to_message") or {}
    if nachricht.get("text") and (nachricht["chat"]["id"], antwort_auf.get("message_id")) in _texteingaben:
        await _neuer_text(lauf, nachricht)
        return
    if nachricht.get("video") or (nachricht.get("document") or {}).get("mime_type", "").startswith("video/"):
        await _video_beitrag(lauf, nachricht)
        return
    if nachricht.get("photo") or (nachricht.get("document") or {}).get("mime_type", "").startswith("image/"):
        await _beitrag(lauf, nachricht)
        return
    gefunden = aktionsseite_link.finden(nachricht.get("text"))
    if gefunden is not None:
        await _link_beitrag(lauf, nachricht, *gefunden)


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
    anleitung = await lauf.antworten(nachricht, _anleitung(seite, konvoi))
    if thema is None:
        await _einrichten(lauf, chat_id, seite, konvoi, anleitung.get("message_id"))


def _minuten(seite: PublicTracker) -> int:
    return max(seite.delay_minutes, aktionsseite.MIN_VERZOEGERUNG_MIN)


def _anleitung(seite: PublicTracker, konvoi: PublicTrackerConvoy) -> str:
    return TEXT_VERBUNDEN.format(konvoi=konvoi.display_name, seite=seite.title, minuten=_minuten(seite))


async def _einrichten(
    lauf: _Lauf, chat_id: int, seite: PublicTracker, konvoi: PublicTrackerConvoy, anleitung_id: int | None
) -> None:
    """Beschreibung, Bild, Anleitung — und ein Satz, wenn Rechte fehlen."""
    fehlt = await aktionsseite_gruppe.einrichten(
        lauf.api, chat_id, seite=seite.title, konvoi=konvoi.display_name,
        minuten=_minuten(seite), farbe=konvoi.color, anleitung_id=anleitung_id,
    )
    if fehlt:
        await lauf.api.senden(chat_id, aktionsseite_gruppe.TEXT_RECHTE.format(rechte=", ".join(fehlt)))


async def _ich_in_gruppe(lauf: _Lauf, mitglied: dict) -> None:
    """Der Bot kommt in eine Gruppe oder wird dort Admin."""
    chat = mitglied.get("chat") or {}
    if chat.get("type") not in ("group", "supergroup"):
        return
    vorher = (mitglied.get("old_chat_member") or {}).get("status")
    jetzt = (mitglied.get("new_chat_member") or {}).get("status")
    gebunden, seite = await _bindung(lauf, chat["id"], None)
    if vorher in ("left", "kicked", None) and jetzt in ("member", "administrator"):
        if gebunden is None:
            text_ = TEXT_HALLO.format(
                rechte=f"{aktionsseite_gruppe.RECHT_INFO}, {aktionsseite_gruppe.RECHT_ANHEFTEN}"
            )
            if not lauf.ich.liest_alles and jetzt != "administrator":
                text_ += TEXT_HALLO_PRIVAT
            await lauf.api.senden(chat["id"], text_)
            return
    if jetzt != "administrator" or vorher == "administrator" or gebunden is None:
        return
    # Rechte kamen nach dem Verbinden: jetzt nachholen, mit frischer Anleitung.
    konvoi = await lauf.db.get(PublicTrackerConvoy, (gebunden.tracker_id, gebunden.convoy_id))
    if konvoi is None or not await _seite_offen(lauf, seite):
        return
    anleitung = await lauf.api.senden(chat["id"], _anleitung(seite, konvoi))
    await _einrichten(lauf, chat["id"], seite, konvoi, anleitung.get("message_id"))


async def _begruessen(lauf: _Lauf, nachricht: dict, neu: list[dict]) -> None:
    chat_id = nachricht["chat"]["id"]
    gebunden, seite = await _bindung(lauf, chat_id, None)
    if not neu or gebunden is None or not await _seite_offen(lauf, seite):
        return
    jetzt = time.monotonic()
    zuletzt = _willkommen.get(chat_id)
    if zuletzt and jetzt - zuletzt[0] < WILLKOMMEN_PAUSE.total_seconds():
        return
    namen = [_name(m) for m in neu[:5]]
    if len(neu) > 5:
        namen.append("und alle anderen")
    gesendet = await lauf.api.senden(
        chat_id, TEXT_WILLKOMMEN.format(namen=", ".join(namen), seite=seite.title, minuten=_minuten(seite))
    )
    _willkommen[chat_id] = (jetzt, gesendet.get("message_id"))
    if zuletzt:
        try:
            await lauf.api.loeschen(chat_id, zuletzt[1])
        except TelegramFehler:
            pass  # älter als 48 h oder schon weg — dann bleibt sie eben stehen


async def _seite_offen(lauf: _Lauf, seite: PublicTracker) -> bool:
    return aktionsseite.ist_aktiv(seite, lauf.jetzt) and await org_module.freigegeben(
        lauf.db, seite.organization_id, org_module.AKTIONSSEITEN
    )


async def _beitrag(lauf: _Lauf, nachricht: dict) -> None:
    chat_id = nachricht["chat"]["id"]
    chat, seite = await _bindung(lauf, chat_id, _thema(nachricht))
    if chat is None:
        return  # Eine fremde Gruppe bekommt nicht einmal eine Antwort.
    if not await _seite_offen(lauf, seite):
        await _ansagen(lauf, nachricht, chat, "seite_zu", TEXT_SEITE_ZU.format(seite=seite.title))
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
        await _ansagen(lauf, nachricht, chat, "tagesgrenze",
                       TEXT_TAGESGRENZE.format(was="Fotos", n=BILDER_JE_TAG))
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
            sender_telegram_id=von.get("id"), sender_name=_absender(seite, von),
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
        await _karte_senden(lauf.db, lauf.api, post, _thema(nachricht), lauf.jetzt)
    else:
        await karte_aktualisieren(lauf.db, lauf.api, post, lauf.jetzt)


async def _link_beitrag(
    lauf: _Lauf, nachricht: dict, link: aktionsseite_link.Link, text_: str | None
) -> None:
    """Ein Link statt eines Fotos (§ 11). Als Antwort auf einen Beitrag gehört
    er zu dessen Zeitpunkt und damit zu dessen Ort — sonst zur Zeit der
    Nachricht. Freigabe, Verzögerung und Platzierung wie bei Fotos."""
    chat_id = nachricht["chat"]["id"]
    chat, seite = await _bindung(lauf, chat_id, _thema(nachricht))
    if chat is None:
        return
    if not await _seite_offen(lauf, seite):
        await _ansagen(lauf, nachricht, chat, "seite_zu", TEXT_SEITE_ZU.format(seite=seite.title))
        return
    if nachricht.get("forward_origin") or nachricht.get("forward_date"):
        return
    if await _links_heute(lauf, chat_id) >= LINKS_JE_TAG:
        logger.info("Telegram: Tagesgrenze für Links in Chat %s erreicht", chat_id)
        await _ansagen(lauf, nachricht, chat, "linkgrenze",
                       TEXT_TAGESGRENZE.format(was="Links", n=LINKS_JE_TAG))
        return
    zeit = datetime.fromtimestamp(nachricht["date"], timezone.utc)
    bezug = (nachricht.get("reply_to_message") or {}).get("message_id")
    if bezug is not None:
        vorher = (await lauf.db.execute(
            select(PublicTrackerPost).where(
                PublicTrackerPost.chat_id == chat_id,
                PublicTrackerPost.tracker_id == chat.tracker_id,
                PublicTrackerPost.convoy_id == chat.convoy_id,
                (PublicTrackerPost.message_id == bezug) | (PublicTrackerPost.card_message_id == bezug),
            ).limit(1)
        )).scalar_one_or_none()
        if vorher is not None:
            zeit = vorher.taken_at
    von = nachricht.get("from") or {}
    # Vor dem Anlegen: Die Karte soll gleich sagen, ob ein Bild mit hinausgeht.
    vorschau = await aktionsseite_vorschau.holen(link)
    post = PublicTrackerPost(
        public_id=secrets.token_urlsafe(16), tracker_id=chat.tracker_id, convoy_id=chat.convoy_id,
        quelle="telegram", chat_id=chat_id, message_id=nachricht["message_id"],
        taken_at=zeit, status="wartet", text_raw=text_, text_public=kuerzen(text_),
        link_url=link.url, link_dienst=link.dienst,
        sender_telegram_id=von.get("id"), sender_name=_absender(seite, von),
        photos=[],
    )
    lauf.db.add(post)
    if vorschau is not None:
        # Das einzige Bild eines Link-Beitrags ist seine Vorschau (§ 11.2).
        foto = PublicTrackerPhoto(
            public_id=secrets.token_urlsafe(16), position=0,
            width=vorschau.breite, height=vorschau.hoehe,
        )
        post.photos.append(foto)
        await lauf.db.flush()
        lauf.db.add(PublicTrackerPhotoData(photo_id=foto.id, gross=vorschau.gross, klein=vorschau.klein))
    try:
        await lauf.db.commit()
    except IntegrityError:
        await lauf.db.rollback()
        return
    await _karte_senden(lauf.db, lauf.api, post, _thema(nachricht), lauf.jetzt)


async def _links_heute(lauf: _Lauf, chat_id: int) -> int:
    return (await lauf.db.execute(
        select(func.count()).select_from(PublicTrackerPost).where(
            PublicTrackerPost.chat_id == chat_id,
            PublicTrackerPost.link_url.is_not(None),
            PublicTrackerPost.created_at > lauf.jetzt - timedelta(days=1),
        )
    )).scalar_one()


# Was der Medien-Container dekodiert (``--enable-decoder`` in docker/medien);
# AV1 nicht.
_VIDEO_CODECS = {"h264", "h265", "hevc", "vp9"}


def video_fassung(datei: dict) -> dict | None:
    """Welche Fassung eines Videos geholt wird — oder ``None``, wenn keine
    unter die 20 MB von ``getFile`` passt.

    Das Original, solange es passt. Sonst eine der kleineren Fassungen, die
    Telegram selbst anlegt (``qualities``): Ein Clip vom Telefon in voller
    Qualität ist nach wenigen Sekunden größer als 20 MB, und hier wird ohnehin
    auf 720p umgerechnet. Unter den passenden die kleinste mit mindestens 720
    Pixeln an der kurzen Seite, sonst die größte. Eine Fassung ohne Größe zählt
    nicht — 20 MB ist eine Grenze von Telegram, nicht von hier.
    """
    grenze = aktionsseite_video.MAX_EINGANG
    if (datei.get("file_size") or 0) <= grenze:
        return datei
    passend = [
        q for q in datei.get("qualities") or []
        if isinstance(q, dict) and q.get("file_id") and q.get("codec") in _VIDEO_CODECS
        and 0 < (q.get("file_size") or 0) <= grenze
    ]
    if not passend:
        return None

    def kurz(q: dict) -> int:
        return min(q.get("width") or 0, q.get("height") or 0)

    genug = [q for q in passend if kurz(q) >= 720]
    if genug:
        return min(genug, key=lambda q: q["file_size"])
    return max(passend, key=lambda q: (kurz(q), q["file_size"]))


async def _video_beitrag(lauf: _Lauf, nachricht: dict) -> None:
    """Ein Video (§ 15): neu kodiert im Medien-Container, abgelegt als Datei,
    das Standbild als einziges Bild. Freigabe, Verzögerung und Platzierung wie
    bei Fotos. Ein Video im Album wird ein eigener Beitrag — ein Beitrag hat
    Fotos oder ein Video, nie beides."""
    chat_id = nachricht["chat"]["id"]
    chat, seite = await _bindung(lauf, chat_id, _thema(nachricht))
    if chat is None:
        return
    if not await _seite_offen(lauf, seite):
        await _ansagen(lauf, nachricht, chat, "seite_zu", TEXT_SEITE_ZU.format(seite=seite.title))
        return
    if nachricht.get("forward_origin") or nachricht.get("forward_date"):
        return
    if not aktionsseite_video.an():
        await _ansagen(lauf, nachricht, chat, "video_aus", TEXT_VIDEO_AUS)
        return
    datei = nachricht.get("video") or nachricht["document"]
    # Was Telegram vorab sagt, spart den Abruf: zu lang, zu groß (und dann
    # vielleicht eine kleinere Fassung).
    if (datei.get("duration") or 0) > aktionsseite_video.MAX_SEKUNDEN:
        await lauf.antworten(nachricht, TEXT_VIDEO_ZU_LANG)
        return
    fassung = video_fassung(datei)
    if fassung is None:
        await lauf.antworten(nachricht, TEXT_VIDEO_ZU_GROSS)
        return
    if await _videos_heute(lauf, chat_id) >= VIDEOS_JE_TAG:
        logger.info("Telegram: Tagesgrenze für Videos in Chat %s erreicht", chat_id)
        await _ansagen(lauf, nachricht, chat, "videogrenze",
                       TEXT_TAGESGRENZE.format(was="Videos", n=VIDEOS_JE_TAG))
        return
    try:
        video = await aktionsseite_video.umwandeln(await lauf.api.datei(fassung["file_id"]))
    except aktionsseite_video.VideoFehler as e:
        logger.info("Telegram: Video nicht übernommen (%s)", e)
        await lauf.antworten(nachricht, str(e))
        return
    except TelegramFehler as e:
        logger.info("Telegram: Video nicht geholt (%s)", e.beschreibung)
        await lauf.antworten(nachricht, TEXT_VIDEO_ZU_GROSS if e.code == 400 else TEXT_VIDEO_FEHLT)
        return

    unterschrift = nachricht.get("caption")
    von = nachricht.get("from") or {}
    post = PublicTrackerPost(
        public_id=secrets.token_urlsafe(16), tracker_id=chat.tracker_id, convoy_id=chat.convoy_id,
        quelle="telegram", chat_id=chat_id, message_id=nachricht["message_id"],
        taken_at=datetime.fromtimestamp(nachricht["date"], timezone.utc),
        status="wartet", text_raw=unterschrift, text_public=kuerzen(unterschrift),
        sender_telegram_id=von.get("id"), sender_name=_absender(seite, von),
        photos=[],
    )
    lauf.db.add(post)
    foto = PublicTrackerPhoto(
        public_id=secrets.token_urlsafe(16), position=0,
        width=video.poster.breite, height=video.poster.hoehe,
    )
    post.photos.append(foto)
    eintrag = PublicTrackerVideo(
        public_id=secrets.token_urlsafe(16), width=video.breite, height=video.hoehe,
        seconds=video.sekunden, sound=video.ton, bytes=len(video.mp4),
    )
    post.video = eintrag
    await lauf.db.flush()
    lauf.db.add(PublicTrackerPhotoData(photo_id=foto.id, gross=video.poster.gross, klein=video.poster.klein))
    # Erst die Datei, dann die Zeile: Eine Zeile ohne Datei wäre ein Loch auf
    # der Seite, eine Datei ohne Zeile räumt ``aufraeumen`` weg.
    aktionsseite_video.ablegen(eintrag.public_id, video.mp4)
    try:
        await lauf.db.commit()
    except IntegrityError:
        await lauf.db.rollback()
        aktionsseite_video.loeschen(eintrag.public_id)
        return
    await _karte_senden(lauf.db, lauf.api, post, _thema(nachricht), lauf.jetzt)


async def _videos_heute(lauf: _Lauf, chat_id: int) -> int:
    return (await lauf.db.execute(
        select(func.count()).select_from(PublicTrackerVideo).join(PublicTrackerPost).where(
            PublicTrackerPost.chat_id == chat_id,
            PublicTrackerPost.created_at > lauf.jetzt - timedelta(days=1),
        )
    )).scalar_one()


async def _ansagen(lauf: _Lauf, nachricht: dict, chat: PublicTrackerChat, grund: str, text_: str) -> None:
    """Sagt der Gruppe, warum ihre Fotos nicht ankommen — einmal je Grund und
    ``ANSAGE_WIEDER``, nicht auf jedes Bild eines Albums. Still verwerfen hieße,
    dass die Fahrer weiter posten und sich wundern."""
    if chat.ansage_grund == grund and chat.ansage_at and chat.ansage_at > lauf.jetzt - ANSAGE_WIEDER:
        return
    chat.ansage_grund, chat.ansage_at = grund, lauf.jetzt
    await lauf.db.commit()
    try:
        await lauf.antworten(nachricht, text_)
    except TelegramFehler as e:
        # Eine Ansage holt niemand nach; das nächste Foto nach der Frist sagt es wieder.
        logger.info("Telegram: Ansage nicht gesendet (%s)", e.beschreibung)


async def _bilder_heute(lauf: _Lauf, chat_id: int) -> int:
    return (await lauf.db.execute(
        select(func.count()).select_from(PublicTrackerPhoto).join(PublicTrackerPost).where(
            PublicTrackerPost.chat_id == chat_id,
            # Vorschaubilder zählen bei den Links (``LINKS_JE_TAG``), nicht hier,
            # Standbilder bei den Videos (``VIDEOS_JE_TAG``).
            PublicTrackerPost.link_url.is_(None),
            ~PublicTrackerPost.video.has(),
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
        # Nur der Vorname: Die Gruppe sieht die Karte, die Adresse geht sie nichts an.
        u = await db.get(User, post.reviewed_by_user_id)
        pruefer = f"{u.first_name} (ConvoyPlan)" if u and u.first_name else "ConvoyPlan"
    bilder = (await db.execute(
        select(func.count()).select_from(PublicTrackerPhoto).where(PublicTrackerPhoto.post_id == post.id)
    )).scalar_one()
    video = (await db.execute(
        select(PublicTrackerVideo).where(PublicTrackerVideo.post_id == post.id)
    )).scalar_one_or_none()
    return karte(
        post, konvoi=konvoi.display_name if konvoi else "?", bilder=bilder,
        verzoegerung_min=seite.delay_minutes, pruefer=pruefer, jetzt=jetzt, video=video,
    )


def _spaeter_versuchen(e: TelegramFehler) -> bool:
    """Gedrosselt, Netz weg oder Telegram gestört: die Karte kommt später. Alles
    andere (Bot aus der Gruppe geworfen, Nachricht gelöscht) wird nicht besser."""
    return e.code in (0, 429) or e.code >= 500


async def _nachholen(db: AsyncSession, post: PublicTrackerPost, e: TelegramFehler, jetzt: datetime) -> None:
    post.karte_faellig_ab = jetzt + timedelta(seconds=max(e.warten or 30, 1))
    await db.commit()
    logger.info("Telegram: Karte für Beitrag %s später (%s)", post.id, e.beschreibung)


async def _thema_von(db: AsyncSession, post: PublicTrackerPost) -> int | None:
    return (await db.execute(
        select(PublicTrackerChat.thread_id).where(
            PublicTrackerChat.tracker_id == post.tracker_id,
            PublicTrackerChat.convoy_id == post.convoy_id,
            PublicTrackerChat.chat_id == post.chat_id,
        )
    )).scalar_one_or_none()


async def _karte_senden(
    db: AsyncSession, api: TelegramApi, post: PublicTrackerPost, thread_id: int | None,
    jetzt: datetime | None = None,
) -> None:
    """Die eine Karte je Beitrag, als Antwort auf ihn. Kommt sie nicht an, steht
    der Beitrag in der Warteschlange (``karte_faellig_ab``) — ohne Karte
    könnte die Presse ihn in Telegram nicht freigeben."""
    jetzt = jetzt or datetime.now(timezone.utc)
    text_, knoepfe = await _karte(db, post, jetzt)
    try:
        gesendet = await api.senden(
            post.chat_id, text_, thread_id=thread_id, antwort_auf=post.message_id, knoepfe=knoepfe,
        )
    except TelegramFehler as e:
        if _spaeter_versuchen(e):
            await _nachholen(db, post, e, jetzt)
        else:
            logger.info("Telegram: Karte nicht gesendet (%s)", e.beschreibung)
        return
    post.card_message_id = gesendet["message_id"]
    post.karte_faellig_ab = None
    await db.commit()


async def karte_aktualisieren(
    db: AsyncSession, api: TelegramApi, post: PublicTrackerPost, jetzt: datetime | None = None
) -> None:
    """Die Karte in der Gruppe auf den Stand bringen — auch nach einer
    Änderung im Org-Admin (§ 8.3). Gedrosselt kommt sie in die Warteschlange
    und wird dann aus dem **dann** gültigen Stand gebaut, nicht aus dem jetzigen."""
    if post.chat_id is None:
        return
    jetzt = jetzt or datetime.now(timezone.utc)
    if post.card_message_id is None:
        await _karte_senden(db, api, post, await _thema_von(db, post), jetzt)
        return
    text_, knoepfe = await _karte(db, post, jetzt)
    try:
        await api.bearbeiten(post.chat_id, post.card_message_id, text_, knoepfe)
    except TelegramFehler as e:
        if _spaeter_versuchen(e):
            await _nachholen(db, post, e, jetzt)
            return
        logger.info("Telegram: Karte nicht bearbeitet (%s)", e.beschreibung)
    if post.karte_faellig_ab is not None:
        post.karte_faellig_ab = None
        await db.commit()


async def karten_nachholen(db: AsyncSession, api: TelegramApi, org_id: uuid.UUID,
                           jetzt: datetime | None = None) -> int:
    """Karten, die Telegram gedrosselt hat, nachholen — die ältesten zuerst.
    Drosselt Telegram wieder, endet der Durchgang: der Rest wartet ohnehin."""
    jetzt = jetzt or datetime.now(timezone.utc)
    faellig = (await db.execute(
        select(PublicTrackerPost)
        .join(PublicTracker, PublicTracker.id == PublicTrackerPost.tracker_id)
        .where(PublicTracker.organization_id == org_id, PublicTrackerPost.karte_faellig_ab <= jetzt)
        .order_by(PublicTrackerPost.karte_faellig_ab)
        .limit(KARTEN_JE_DURCHGANG)
    )).scalars().all()
    erledigt = 0
    for post in faellig:
        await karte_aktualisieren(db, api, post, jetzt)
        if post.karte_faellig_ab is not None:
            break
        erledigt += 1
    return erledigt


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
    # Zurückziehen soll sofort wirken, nicht erst nach dem Zwischenspeicher.
    from app.api.routes.aktionsseite import _vergessen

    _vergessen(seite.slug)
    await lauf.api.quittieren(cq["id"], {
        "frei": "Freigegeben — erscheint nach der Verzögerung.",
        "ablehnen": "Abgelehnt.",
        "zurueck": "Zurückgezogen.",
    }[aktion])
    await karte_aktualisieren(lauf.db, lauf.api, post, lauf.jetzt)


async def _ab(lauf: _Lauf, nachricht: dict, arg: str) -> None:
    """``/ab 18:00`` als Antwort auf einen Beitrag: später, nie früher (§ 3.5).
    Wie die Knöpfe nur für die Presse dieser Seite."""
    chat_id = nachricht["chat"]["id"]
    bezug = (nachricht.get("reply_to_message") or {}).get("message_id")
    post = None
    if bezug is not None:
        post = (await lauf.db.execute(
            select(PublicTrackerPost).where(
                PublicTrackerPost.chat_id == chat_id,
                (PublicTrackerPost.card_message_id == bezug) | (PublicTrackerPost.message_id == bezug),
            ).limit(1)
        )).scalar_one_or_none()
    if post is None:
        await lauf.antworten(nachricht, TEXT_AB_HILFE)
        return
    seite = await lauf.db.get(PublicTracker, post.tracker_id)
    if seite is None or seite.organization_id != lauf.bot.organization_id:
        return
    von = nachricht.get("from") or {}
    presse = await lauf.db.get(PublicTrackerPresse, (post.tracker_id, von.get("id")))
    if presse is None:
        await lauf.antworten(nachricht, "Terminieren darf nur die Presse.")
        return
    if post.status not in ("wartet", "freigegeben"):
        await lauf.antworten(nachricht, "Der Beitrag ist abgelehnt oder zurückgezogen.")
        return
    if post.public_since is not None:
        await lauf.antworten(
            nachricht, "Der Beitrag ist schon öffentlich. Zurückholen geht mit „Zurückziehen“."
        )
        return
    try:
        termin = termin_lesen(arg, lauf.jetzt)
    except TerminFehler:
        await lauf.antworten(nachricht, TEXT_AB_HILFE)
        return
    regel = regelzeit(post, seite.delay_minutes)
    if termin is not None and termin <= regel:
        # Früher geht nie — kein Fehler, nur die Zeit, die ohnehin gilt.
        termin = None
        antwort = f"Früher als die Verzögerung geht nicht — er erscheint frühestens {_uhrzeit(regel, lauf.jetzt)}."
    elif termin is None:
        antwort = f"Termin entfernt — er erscheint frühestens {_uhrzeit(regel, lauf.jetzt)}."
    else:
        antwort = f"Termin gesetzt — frühestens {_uhrzeit(termin, lauf.jetzt)}."
    post.not_before = termin
    await lauf.db.commit()
    await audit.record(
        lauf.db, AUDIT_TERMIN, org_id=seite.organization_id,
        target_type="aktionsseite_beitrag", target_id=str(post.id),
        detail={"not_before": termin.isoformat() if termin else None,
                "telegram_user_id": von["id"], "name": presse.display_name},
    )
    from app.api.routes.aktionsseite import _vergessen

    _vergessen(seite.slug)
    await lauf.antworten(nachricht, antwort)
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
    if post.link_url is not None:
        # Der Link steht fest; bearbeitet wird nur der Text drumherum.
        gefunden = aktionsseite_link.finden(nachricht.get("text"))
        unterschrift = gefunden[1] if gefunden else (nachricht.get("text") or "").strip() or None
    else:
        unterschrift = nachricht.get("caption")
    post.text_raw = unterschrift
    if post.status == "wartet" and not post.text_edited_by_presse:
        post.text_public = kuerzen(unterschrift)
    await lauf.db.commit()
    await karte_aktualisieren(lauf.db, lauf.api, post, lauf.jetzt)


# ── „Öffentlich seit" ──────────────────────────────────────────────────────


async def oeffentlich_markieren(jetzt: datetime | None = None) -> int:
    """Freigegebene Beiträge, die jetzt hinausgehen, bekommen ``public_since``,
    und ihre Karte in der Gruppe sagt es.

    Entschieden wird mit genau der Antwort, die der EventTracker bekäme
    (``aktionsseite.nutzlast``), nicht mit einer eigenen Regel. Gibt die
    Zahl der neu markierten Beiträge zurück."""
    jetzt = jetzt or datetime.now(timezone.utc)
    markiert = 0
    async with AsyncSessionLocal() as db:
        seiten_ids = set((await db.execute(
            select(PublicTrackerPost.tracker_id).where(
                PublicTrackerPost.status == "freigegeben",
                PublicTrackerPost.public_since.is_(None),
                PublicTrackerPost.taken_at <= jetzt - timedelta(minutes=aktionsseite.MIN_VERZOEGERUNG_MIN),
            )
        )).scalars().all())
        for seite_id in seiten_ids:
            seite = (await db.execute(
                select(PublicTracker).where(PublicTracker.id == seite_id)
                .options(selectinload(PublicTracker.convoys))
            )).scalar_one_or_none()
            if seite is None or not aktionsseite.ist_aktiv(seite, jetzt) or not await org_module.freigegeben(
                db, seite.organization_id, org_module.AKTIONSSEITEN
            ):
                continue
            nutz = await aktionsseite.nutzlast(db, seite, jetzt)
            sichtbar = {p["id"] for k in nutz["convoys"] for p in k["posts"]}
            if not sichtbar:
                continue
            posts = (await db.execute(
                select(PublicTrackerPost).where(
                    PublicTrackerPost.tracker_id == seite_id,
                    PublicTrackerPost.status == "freigegeben",
                    PublicTrackerPost.public_since.is_(None),
                    PublicTrackerPost.public_id.in_(sichtbar),
                )
            )).scalars().all()
            for p in posts:
                p.public_since = jetzt
            await db.commit()
            markiert += len(posts)
            bot = await db.get(PublicTrackerTelegram, seite.organization_id)
            if posts and bot is not None and bot.status != "ungueltig" and settings.telegram_enabled:
                api = api_fuer(decrypt_secret(bot.bot_token_enc))
                for p in posts:
                    await karte_aktualisieren(db, api, p, jetzt)
    return markiert


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
        try:
            await karten_nachholen(db, api, org_id)
        except Exception:
            logger.exception("Telegram: Karten nicht nachgeholt")
            await db.rollback()
    return True


async def _fehler_merken(db: AsyncSession, bot: PublicTrackerTelegram, e: TelegramFehler) -> None:
    bot.status = {401: "ungueltig", 404: "ungueltig", 409: "konflikt"}.get(e.code, "fehler")
    bot.last_error = e.beschreibung
    bot.checked_at = datetime.now(timezone.utc)
    await db.commit()
    logger.warning("Telegram-Bot der Organisation %s: %s", bot.organization_id, e.beschreibung)


async def _befehle_fuer(org_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        bot = await db.get(PublicTrackerTelegram, org_id)
        if bot is None or bot.status == "ungueltig":
            return
        token = decrypt_secret(bot.bot_token_enc)
    await befehle_eintragen(api_fuer(token))


def _sperrschluessel(org_id: uuid.UUID) -> int:
    return int.from_bytes(hashlib.sha256(b"telegram:" + org_id.bytes).digest()[:8], "big", signed=True)


async def _bot_laufen(org_id: uuid.UUID) -> None:
    """Holt für einen Bot ab, solange es ihn gibt — und nur, wenn kein anderer
    Prozess es schon tut."""
    async with engine.connect() as conn:
        if not await conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": _sperrschluessel(org_id)}):
            return
        try:
            # Auch für Bots, die vor den Befehlen eingerichtet wurden; einmal je Start.
            await _befehle_fuer(org_id)
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
    """Startet je eingetragenem Bot eine Abholaufgabe und räumt beendete weg;
    setzt nebenbei „Öffentlich seit" (``oeffentlich_markieren``).

    Eine Aufgabe, die endet (Token ungültig, Modul gesperrt, Bot entfernt), wird
    beim nächsten Durchgang neu gestartet, falls es den Bot noch gibt — ein
    neuer Token setzt den Status zurück."""
    laufend: dict[uuid.UUID, asyncio.Task] = {}
    zuletzt_aufgeraeumt = 0.0
    try:
        while True:
            try:
                await oeffentlich_markieren()
            except Exception:
                logger.exception("Telegram-Schleife: „Öffentlich seit“ nicht gesetzt")
            if time.monotonic() - zuletzt_aufgeraeumt > AUFRAEUMEN_ALLE:
                zuletzt_aufgeraeumt = time.monotonic()
                try:
                    async with AsyncSessionLocal() as db:
                        await aktionsseite_video.aufraeumen(db)
                except Exception:
                    logger.exception("Telegram-Schleife: Videos nicht aufgeräumt")
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
