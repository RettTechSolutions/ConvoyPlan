"""Das Bildschirmfoto einer Meldung — annehmen, ablegen, wieder hergeben.

Der Screenshot kommt als Data-URL im JSON-Körper der Meldung und nicht als
zweiter Multipart-Aufruf. Das ist eine bewusste Wahl: der Browser erzeugt ihn
ohnehin als Data-URL (Bildschirmaufnahme über ein Canvas, Einfügen aus der
Zwischenablage), und ein zweiter Aufruf hieße, dass eine Meldung zwischen
beiden Aufrufen ohne ihr Bild dastehen kann — genau dann, wenn das Netz
wackelt, also genau dann, wenn gemeldet wird. Der Preis sind rund 33 % mehr
Bytes auf der Leitung; bei einer Obergrenze von 4 MB ist das vertretbar.

**Nur Rasterbilder.** PNG, JPEG, WebP — kein SVG. Ein Bildschirmfoto ist nie
ein SVG, und SVG ist das einzige Bildformat, das Skript tragen kann; die
Prüfung, die `branding.py` dafür braucht, muss hier gar nicht erst existieren.
Erkannt wird an den Magic Bytes, nicht am mitgeschickten MIME-Typ: was der
Absender behauptet, entscheidet nichts.

Abgelegt wird unter `FEEDBACK_DIR` auf demselben Volume wie die Logos
(`logo_uploads:/uploads`). Ausgeliefert wird nur an Superadmins, über
`GET /api/admin/feedback/{id}/screenshot` — das Verzeichnis ist nicht
statisch gemountet.
"""

import asyncio
import base64
import binascii
import logging
import re
import uuid
from pathlib import Path

from fastapi import HTTPException

logger = logging.getLogger(__name__)

FEEDBACK_DIR = Path("/uploads/feedback")

# 4 MB Bilddaten. Ein Vollbild in PNG liegt je nach Auflösung bei 1–3 MB; die
# Oberfläche rechnet vorher auf JPEG herunter, wenn es darüber läge.
MAX_SCREENSHOT_BYTES = 4 * 1024 * 1024

# Die Magic Bytes je Endung. WebP ist zweiteilig: "RIFF" + 4 Byte Länge +
# "WEBP" — deshalb ein Prüfschritt und kein reines `startswith`.
_MAGIC_PNG = b"\x89PNG\r\n\x1a\n"
_MAGIC_JPEG = b"\xff\xd8\xff"

_DATA_URL = re.compile(r"^data:image/(png|jpeg|jpg|webp);base64,(?P<daten>[A-Za-z0-9+/=\s]+)$")


def _endung(rohdaten: bytes) -> str:
    """Die Endung, die zum tatsächlichen Inhalt passt — oder HTTP 400."""
    if rohdaten.startswith(_MAGIC_PNG):
        return ".png"
    if rohdaten.startswith(_MAGIC_JPEG):
        return ".jpg"
    if rohdaten[:4] == b"RIFF" and rohdaten[8:12] == b"WEBP":
        return ".webp"
    raise HTTPException(
        status_code=400,
        detail="Das Bildschirmfoto ist kein PNG, JPEG oder WebP.",
    )


def decode_screenshot(data_url: str) -> tuple[bytes, str]:
    """Eine Data-URL in Bytes und Endung zerlegen.

    Wirft HTTP 400, wenn die URL nicht die erwartete Form hat, sich nicht
    dekodieren lässt, zu groß ist oder der Inhalt nicht zu einem der drei
    Rasterformate passt.
    """
    treffer = _DATA_URL.match(data_url.strip())
    if treffer is None:
        raise HTTPException(
            status_code=400,
            detail="Das Bildschirmfoto muss eine Data-URL (PNG, JPEG oder WebP) sein.",
        )
    try:
        rohdaten = base64.b64decode(treffer.group("daten"), validate=False)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Das Bildschirmfoto ließ sich nicht lesen.")
    if not rohdaten:
        raise HTTPException(status_code=400, detail="Das Bildschirmfoto ist leer.")
    # Nach dem Dekodieren geprüft, nicht vorher: die Grenze gilt dem Bild, und
    # eine Base64-Zeichenkette ist ein Drittel länger als das, was in ihr steckt.
    if len(rohdaten) > MAX_SCREENSHOT_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Das Bildschirmfoto ist zu groß (höchstens {MAX_SCREENSHOT_BYTES // (1024 * 1024)} MB).",
        )
    return rohdaten, _endung(rohdaten)


async def store_screenshot(report_id: uuid.UUID, rohdaten: bytes, endung: str) -> str:
    """Die Bytes ablegen und den Dateinamen zurückgeben (ohne Pfad)."""
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{report_id}{endung}"
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, (FEEDBACK_DIR / name).write_bytes, rohdaten)
    return name


def screenshot_path(name: str) -> Path:
    """Der Pfad zu einem abgelegten Bild — nur aus dem Dateinamen gebaut.

    `Path.name` schneidet alles ab, was nach Verzeichnis aussieht. Der Wert
    kommt zwar aus der eigenen Datenbank und nicht von außen, aber ein Pfad,
    der aus einer Spalte zusammengesetzt wird, ist genau die Stelle, an der ein
    späterer Importweg still zu einem Ausbruch aus dem Verzeichnis würde.
    """
    return FEEDBACK_DIR / Path(name).name


def delete_screenshot(name: str | None) -> None:
    """Ein Bild entfernen — best effort.

    Eine verwaiste Datei darf das Löschen der Meldung nicht scheitern lassen;
    die Zeile ist das, worauf es ankommt.
    """
    if not name:
        return
    try:
        screenshot_path(name).unlink()
    except OSError:
        logger.debug("Bildschirmfoto %s ließ sich nicht entfernen", name, exc_info=True)


MEDIENTYPEN = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}


def medientyp(name: str) -> str:
    return MEDIENTYPEN.get(Path(name).suffix.lower(), "application/octet-stream")
