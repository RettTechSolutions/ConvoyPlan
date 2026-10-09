"""Meldungen einer selbst gehosteten Instanz an den Hersteller weiterreichen.

Eine Fehlermeldung aus der Anwendung ist ein Programmfehler, und beheben kann
ihn nur, wer den Code pflegt. Auf dem Hosting-Server ist das derselbe, der die
Meldungen sichtet; auf einer selbst gehosteten Instanz sähe sie nur deren
Betreiber, und beim Hersteller käme nichts an. Deshalb geht jede neue Meldung
dort zusätzlich an ``CENTRAL_URL`` (``POST /api/feedback/eingang``). Die Kopie
auf der Instanz bleibt — ihr Betreiber sieht weiter, was gemeldet wurde.

**Erst speichern, dann senden.** Die Meldung landet zuerst in der eigenen
Datenbank mit ``weiterleitung="offen"``, zugestellt wird danach: sofort im
Hintergrund der Anfrage und, falls das scheitert, alle zehn Minuten erneut.
Andersherum ginge eine Meldung verloren, sobald der zentrale Server nicht
erreichbar ist — und gemeldet wird gerade dann, wenn etwas wackelt.

**Nach 14 Tagen aufgegeben.** Eine Instanz ohne Weg nach außen (Behördennetz)
soll nicht für immer Schlange stehen. Wer das von vornherein weiß, setzt
``CENTRAL_URL=`` leer; dann wird gar nichts vorgemerkt.

**Alte Meldungen werden nicht nachgeschickt.** Vorgemerkt wird nur, was nach
dieser Änderung eingeht; der Dialog nennt seither den Hersteller als
Empfänger. Wer vorher gemeldet hat, las „nur der Betreiber dieser Instanz".

Die Zustellung ist wiederholbar: der Empfänger erkennt eine Meldung an
Instanz und Kennung und legt sie kein zweites Mal an.
"""

import asyncio
import base64
import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.feedback import FeedbackReport
from app.services import betriebsart
from app.services import feedback as feedback_svc

logger = logging.getLogger(__name__)

OFFEN = "offen"
ERLEDIGT = "erledigt"
AUFGEGEBEN = "aufgegeben"

PFAD = "/api/feedback/eingang"
FRIST = timedelta(days=14)
STAPEL = 20
INTERVALL_SEKUNDEN = 600
TIMEOUT_SEKUNDEN = 20.0


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def ziel() -> str | None:
    """Die Adresse, an die weitergeleitet wird — oder ``None``.

    Keine Weiterleitung auf dem Hosting-Server selbst (er *ist* der Empfänger)
    und keine an die eigene Adresse: steht ``INSTANCE_MODE`` dort versehentlich
    auf ``selfhost``, schickte er sich jede Meldung selbst und bekäme ein 404.
    """
    basis = (settings.central_url or "").strip().rstrip("/")
    if not basis or betriebsart.ist_hosting():
        return None
    if _host(basis) and _host(basis) == _host(settings.app_base_url or ""):
        return None
    return basis + PFAD


def ist_aktiv() -> bool:
    return ziel() is not None


async def _screenshot_als_data_url(bericht: FeedbackReport) -> str | None:
    if not bericht.screenshot_name:
        return None
    pfad = feedback_svc.screenshot_path(bericht.screenshot_name)
    try:
        rohdaten = await asyncio.get_running_loop().run_in_executor(None, pfad.read_bytes)
    except OSError:
        # Das Bild ist weg (gelöscht, Volume getauscht) — der Text ist das,
        # worauf es ankommt.
        return None
    typ = feedback_svc.medientyp(bericht.screenshot_name)
    return f"data:{typ};base64,{base64.b64encode(rohdaten).decode()}"


async def nutzlast(bericht: FeedbackReport, instanz_id: str) -> dict:
    """Was beim Hersteller ankommt. Gegenstück: ``schemas.feedback.FeedbackEingang``.

    Was fehlt, fehlt mit Absicht: keine Datenbank-Kennungen von Organisation
    oder Konto (auf dem Empfänger bedeuten sie nichts), keine Notiz und keine
    Priorität des Betreibers.
    """
    return {
        "instanz": instanz_id,
        "instanz_url": settings.app_base_url or None,
        "id": str(bericht.id),
        "kind": bericht.kind,
        "title": bericht.title,
        "description": bericht.description,
        "severity": bericht.severity,
        "org_slug": bericht.org_slug,
        "org_name": bericht.org_name,
        "reporter_email": bericht.reporter_email,
        "reporter_name": bericht.reporter_name,
        "reporter_role": bericht.reporter_role,
        "is_demo": bool(bericht.is_demo),
        "page_url": bericht.page_url,
        "user_agent": bericht.user_agent,
        "app_version": bericht.app_version,
        "viewport": bericht.viewport,
        "screenshot": await _screenshot_als_data_url(bericht),
    }


async def weiterleiten_offene(
    db: AsyncSession,
    *,
    jetzt: datetime | None = None,
    client: httpx.AsyncClient | None = None,
    nur: uuid.UUID | None = None,
) -> int:
    """Einen Stapel offener Meldungen zustellen. Gibt die Zahl der zugestellten zurück.

    ``nur`` beschränkt auf eine Meldung — für den Versuch direkt nach dem
    Absenden, der nicht den ganzen Rückstand mitnehmen soll.
    """
    adresse = ziel()
    if adresse is None:
        return 0
    from app.services.instance import get_or_create_instance_id

    jetzt = jetzt or datetime.now(timezone.utc)
    abfrage = select(FeedbackReport).where(FeedbackReport.weiterleitung == OFFEN)
    if nur is not None:
        abfrage = abfrage.where(FeedbackReport.id == nur)
    abfrage = abfrage.order_by(FeedbackReport.created_at).limit(STAPEL)
    berichte = list((await db.execute(abfrage)).scalars().all())
    if not berichte:
        return 0

    instanz_id = await get_or_create_instance_id(db)
    eigener_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT_SEKUNDEN)
    zugestellt = 0
    try:
        for bericht in berichte:
            if bericht.created_at and jetzt - bericht.created_at > FRIST:
                bericht.weiterleitung = AUFGEGEBEN
                logger.warning("Meldung %s nach %s nicht zugestellt — aufgegeben", bericht.id, FRIST)
                continue
            try:
                antwort = await client.post(adresse, json=await nutzlast(bericht, instanz_id))
            except httpx.HTTPError as exc:
                logger.info("Meldung %s nicht weitergeleitet (%s) — später erneut", bericht.id, exc)
                continue
            if antwort.is_success:
                bericht.weiterleitung = ERLEDIGT
                bericht.weitergeleitet_at = jetzt
                zugestellt += 1
            else:
                logger.info(
                    "Meldung %s nicht weitergeleitet (HTTP %s) — später erneut",
                    bericht.id,
                    antwort.status_code,
                )
    finally:
        if eigener_client:
            await client.aclose()
    await db.commit()
    return zugestellt


async def sofort_weiterleiten(bericht_id: uuid.UUID) -> None:
    """Der erste Versuch, im Hintergrund der Melde-Anfrage.

    Eigene Sitzung, weil die der Anfrage beim Ausführen schon geschlossen ist.
    Ein Fehler hier ist kein Fehler der Meldung — die Schleife holt ihn nach.
    """
    try:
        async with AsyncSessionLocal() as db:
            await weiterleiten_offene(db, nur=bericht_id)
    except Exception:
        logger.warning("Sofortige Weiterleitung von %s gescheitert — die Schleife holt sie nach", bericht_id, exc_info=True)


async def weiterleitung_loop() -> None:
    """Hintergrundschleife aus dem App-Lifespan. Schläft zuerst."""
    while True:
        await asyncio.sleep(INTERVALL_SEKUNDEN)
        if not ist_aktiv():
            continue
        try:
            async with AsyncSessionLocal() as db:
                await weiterleiten_offene(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Weiterleitung der Meldungen fehlgeschlagen — nächster Versuch in %ss", INTERVALL_SEKUNDEN)
