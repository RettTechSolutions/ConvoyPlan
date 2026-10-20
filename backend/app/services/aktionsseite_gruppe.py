"""Aktionsseite: der Bot richtet die Telegram-Gruppe eines Konvois ein.

Nach ``/verbinden`` (und noch einmal, sobald er dort Admin wird) setzt der Bot
Beschreibung und Gruppenbild und heftet seine Anleitung an. Den **Titel** lässt
er stehen: Unter dem Namen kennen die Fahrer ihre Gruppe, und oft gab es sie
schon vor der Aktion.

Nur für eine ganze Gruppe, nicht für ein Thema — Bild und Beschreibung gälten
sonst für alle Konvois, die sich die Gruppe teilen.

Das Bild ist gezeichnet, nicht hochgeladen: Konvoifarbe der Seite mit den
Anfangsbuchstaben des öffentlichen Namens. Logos der Organisation liegen oft
als SVG vor, und das Backend rastert keine.

Fehlen dem Bot die Rechte, sagt er es; einrichten scheitert nie am Verbinden.
"""
import io
import logging
import re

from PIL import Image, ImageDraw, ImageFont

from app.services.telegram import TelegramApi, TelegramFehler

logger = logging.getLogger(__name__)

RECHT_INFO = "Gruppeninfo ändern"
RECHT_ANHEFTEN = "Nachrichten anheften"

BESCHREIBUNG_MAX = 255  # Grenze von Telegram
BILD_KANTE = 640
STANDARDFARBE = "#E23D28"
_SCHRIFT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_FARBE = re.compile(r"^#[0-9a-fA-F]{6}$")
# Steht vor fast jedem Namen und unterscheidet nichts.
_FUELLWORTE = {"konvoi", "hilfskonvoi", "convoy", "der", "die", "das"}

TEXT_RECHTE = (
    "Für Gruppenbild, Beschreibung und die angeheftete Anleitung brauche ich hier "
    "Adminrechte ({rechte}). Sobald ich sie habe, hole ich das nach."
)


def _kurz(text_: str, n: int) -> str:
    return text_ if len(text_) <= n else text_[: n - 1] + "…"


def beschreibung(seite: str, konvoi: str, minuten: int) -> str:
    text_ = (
        f"Fotos, Videos und Links von „{_kurz(konvoi, 40)}“ für die Aktionsseite „{_kurz(seite, 50)}“. "
        f"Öffentlich erst nach Freigabe durch die Presse, mindestens {minuten} Minuten "
        "verzögert und nie genauer als die Karte."
    )
    return _kurz(text_, BESCHREIBUNG_MAX)


def kuerzel(name: str) -> str:
    worte = re.findall(r"[^\W_]+", name)
    bedeutend = [w for w in worte if w.lower() not in _FUELLWORTE] or worte
    return "".join(w[0] for w in bedeutend[:2]).upper() or "?"


def _vordergrund(farbe: tuple[int, int, int]) -> tuple[int, int, int]:
    r, g, b = farbe
    hell = 0.299 * r + 0.587 * g + 0.114 * b
    return (30, 30, 30) if hell > 160 else (255, 255, 255)


def gruppenbild(name: str, farbe: str | None) -> bytes:
    """Quadratisches JPEG; Telegram schneidet es rund zu, deshalb mittig."""
    hex_ = farbe if farbe and _FARBE.match(farbe) else STANDARDFARBE
    grund = tuple(int(hex_[i : i + 2], 16) for i in (1, 3, 5))
    bild = Image.new("RGB", (BILD_KANTE, BILD_KANTE), grund)
    zeichen = ImageDraw.Draw(bild)
    text_ = kuerzel(name)
    schrift = ImageFont.truetype(_SCHRIFT, 300 if len(text_) == 1 else 240)
    zeichen.text(
        (BILD_KANTE / 2, BILD_KANTE / 2), text_, font=schrift, fill=_vordergrund(grund), anchor="mm"
    )
    puffer = io.BytesIO()
    bild.save(puffer, format="JPEG", quality=90)
    return puffer.getvalue()


def _keine_rechte(e: TelegramFehler) -> bool:
    b = e.beschreibung.lower()
    return e.code in (400, 403) and ("rights" in b or "admin_required" in b or "not an administrator" in b)


async def einrichten(
    api: TelegramApi,
    chat_id: int,
    *,
    seite: str,
    konvoi: str,
    minuten: int,
    farbe: str | None,
    anleitung_id: int | None,
) -> list[str]:
    """Beschreibung, Bild, Anleitung anheften. Zurück kommen die fehlenden Rechte."""
    schritte = [
        (RECHT_INFO, lambda: api.beschreibung_setzen(chat_id, beschreibung(seite, konvoi, minuten))),
        (RECHT_INFO, lambda: api.bild_setzen(chat_id, gruppenbild(konvoi, farbe))),
    ]
    if anleitung_id is not None:
        schritte.append((RECHT_ANHEFTEN, lambda: api.anheften(chat_id, anleitung_id)))
    fehlt: list[str] = []
    for recht, schritt in schritte:
        try:
            await schritt()
        except TelegramFehler as e:
            if _keine_rechte(e):
                if recht not in fehlt:
                    fehlt.append(recht)
            else:
                logger.warning("Telegram: Gruppe %s nicht eingerichtet: %s", chat_id, e.beschreibung)
    return fehlt
