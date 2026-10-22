"""Videos für Beiträge der Aktionsseite: neu kodiert im Medien-Container,
abgelegt als Datei, Standbild wie ein Foto.

Plan: docs/superpowers/plans/2026-10-13-fotos-auf-der-aktionsseite.md, § 15.

Wie bei Fotos geht nie das Original hinaus. Ein Handyvideo trägt GPS-Position,
Gerät und Aufnahmezeit in Boxen des Containers; der Medien-Container
(``docker/medien``) schreibt ein neues MP4 (H.264/AAC, höchstens 1280 Pixel
lange Kante, 30 Bilder/s, ``+faststart``), in dem es diese Boxen nicht gibt.
Er läuft getrennt vom Backend, weil sein ffmpeg mit x264 unter der GPL steht.

Der **Ton** bleibt (entschieden am 15. Oktober) — der EventTracker spielt
stumm ab, bis jemand ihn einschaltet. Die Karte des Bots sagt der Presse, dass
sie vor dem Freigeben hinhören muss: Durchsagen und Gespräche verraten Orte,
die das Bild nicht zeigt.

Die Datei liegt unter ``VIDEOS_DIR`` auf dem Upload-Volume, nicht in der
Datenbank. Gelöscht wird sie nicht dort, wo die Zeile fällt — das sind zu viele
Wege, und die Retention läuft in einem Container ohne das Volume —, sondern von
``aufraeumen``: Was keine Zeile mehr hat, geht.
"""
import base64
import binascii
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.public_tracker import PublicTrackerVideo
from app.services import aktionsseite_bild

logger = logging.getLogger(__name__)

VIDEOS_DIR = Path("/uploads/aktionsseite/videos")
MAX_SEKUNDEN = 60
# Größer liefert Telegram einem Bot nicht (getFile).
MAX_EINGANG = 20 * 1024 * 1024
# Was zurückkommt, ist bei 60 s und 1,5 Mbit/s um 12 MB; mehr ist ein Fehler.
MAX_AUSGANG = 25 * 1024 * 1024
# Ein Video kostet im Medien-Container zehn bis sechzig Sekunden; wartet dort
# schon eins, kommt die Wartezeit dazu.
TIMEOUT = httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0)
# Was jünger ist, kann gerade geschrieben werden, bevor seine Zeile steht.
AUFRAEUMEN_AB = 30 * 60
# Nur in Tests gesetzt (``httpx.MockTransport``).
transport: httpx.AsyncBaseTransport | None = None


class VideoFehler(ValueError):
    """Kein brauchbares Video — der Bot sagt der Gruppe genau diesen Satz."""


@dataclass(frozen=True)
class Video:
    mp4: bytes
    poster: aktionsseite_bild.Bild
    breite: int
    hoehe: int
    sekunden: float
    ton: bool


def an() -> bool:
    return bool(settings.medien_url)


def _ist_mp4(daten: bytes) -> bool:
    return len(daten) > 12 and daten[4:8] == b"ftyp"


async def umwandeln(daten: bytes) -> Video:
    """Die Bytes aus Telegram durch den Medien-Container — oder ``VideoFehler``."""
    if len(daten) > MAX_EINGANG:
        raise VideoFehler("Das Video ist zu groß.")
    try:
        async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT) as client:
            r = await client.post(
                f"{settings.medien_url.rstrip('/')}/video",
                params={"max_sekunden": MAX_SEKUNDEN},
                content=daten,
                headers={"Content-Type": "application/octet-stream"},
            )
    except httpx.HTTPError as e:
        logger.warning("Medien-Container nicht erreichbar (%s)", type(e).__name__)
        raise VideoFehler("Videos können gerade nicht verarbeitet werden. Bitte später noch einmal.") from e
    if r.status_code == 422:
        grund = (r.json() if r.headers.get("content-type", "").startswith("application/json") else {})
        raise VideoFehler(str(grund.get("grund") or "Das Video lässt sich nicht verwenden.")[:200])
    if r.status_code != 200:
        logger.warning("Medien-Container antwortet mit HTTP %s", r.status_code)
        raise VideoFehler("Videos können gerade nicht verarbeitet werden. Bitte später noch einmal.")
    try:
        d = r.json()
        mp4 = base64.b64decode(d["video"], validate=True)
        jpeg = base64.b64decode(d["poster"], validate=True)
        breite, hoehe = int(d["breite"]), int(d["hoehe"])
        sekunden, ton = float(d["sekunden"]), bool(d["ton"])
    except (ValueError, KeyError, TypeError, binascii.Error) as e:
        raise VideoFehler("Das Video lässt sich nicht verwenden.") from e
    # Dem Container wird geglaubt, was er tut — aber nicht, was er schickt.
    if not _ist_mp4(mp4) or len(mp4) > MAX_AUSGANG:
        raise VideoFehler("Das Video lässt sich nicht verwenden.")
    if not (0 < breite <= 1280 and 0 < hoehe <= 1280 and 0 < sekunden <= MAX_SEKUNDEN + 1):
        raise VideoFehler("Das Video lässt sich nicht verwenden.")
    try:
        poster = aktionsseite_bild.verarbeiten(jpeg)
    except aktionsseite_bild.BildFehler as e:
        raise VideoFehler("Das Video lässt sich nicht verwenden.") from e
    return Video(mp4=mp4, poster=poster, breite=breite, hoehe=hoehe, sekunden=sekunden, ton=ton)


_KENNUNG = re.compile(r"[A-Za-z0-9_-]{1,64}")


def pfad(public_id: str) -> Path:
    """Die Datei zu einer Kennung. Eine Kennung, die keine ist (Pfadtrenner,
    ``..``), wirft — sie darf nie zu einem Pfad außerhalb von ``VIDEOS_DIR``
    werden, auch wenn alle Aufrufer sie heute aus der Datenbank nehmen."""
    if not _KENNUNG.fullmatch(public_id):
        raise ValueError("Ungültige Video-Kennung")
    wurzel = os.path.realpath(VIDEOS_DIR)
    ziel = os.path.realpath(os.path.join(wurzel, f"{public_id}.mp4"))
    # Zweiter Riegel neben der Kennung: auch ein Symlink im Verzeichnis darf
    # nicht aus ``VIDEOS_DIR`` hinausführen.
    if not ziel.startswith(wurzel + os.sep):
        raise ValueError("Ungültige Video-Kennung")
    return Path(ziel)


def ablegen(public_id: str, mp4: bytes) -> None:
    """Erst vollständig unter anderem Namen, dann umbenannt: Halbe Dateien
    liefert der Endpunkt nie aus."""
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    ziel = pfad(public_id)
    zwischen = ziel.with_suffix(f".{uuid.uuid4().hex}.tmp")
    zwischen.write_bytes(mp4)
    os.replace(zwischen, ziel)


def loeschen(public_id: str) -> None:
    pfad(public_id).unlink(missing_ok=True)


async def aufraeumen(db: AsyncSession, jetzt: float | None = None) -> int:
    """Dateien ohne Zeile löschen — und Reste abgebrochener Schreibvorgänge.
    Nur, was älter ist als ``AUFRAEUMEN_AB``: Ein Video wird geschrieben, bevor
    seine Zeile festgeschrieben ist."""
    if not VIDEOS_DIR.is_dir():
        return 0
    jetzt = jetzt if jetzt is not None else time.time()
    bekannt = set((await db.execute(select(PublicTrackerVideo.public_id))).scalars().all())
    weg = 0
    for datei in VIDEOS_DIR.iterdir():
        if not datei.is_file():
            continue
        name = datei.name
        kennung = name.removesuffix(".mp4") if name.endswith(".mp4") else None
        if kennung in bekannt:
            continue
        try:
            if jetzt - datei.stat().st_mtime < AUFRAEUMEN_AB:
                continue
            datei.unlink()
            weg += 1
        except FileNotFoundError:
            continue
    if weg:
        logger.info("Aktionsseite: %d Videodatei(en) ohne Beitrag gelöscht", weg)
    return weg
