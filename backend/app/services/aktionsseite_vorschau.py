"""Vorschaubilder für Link-Beiträge: einmal beim Eingang geholt, neu kodiert,
gespeichert wie ein Foto.

Plan: docs/superpowers/plans/2026-10-13-fotos-auf-der-aktionsseite.md, § 11.2.

Der EventTracker lädt nichts von außen. Ein Vorschaubild kommt deshalb nicht
vom Dienst in den Browser, sondern einmal vom Dienst hierher: geholt, wenn der
Link in der Gruppe ankommt, durch ``aktionsseite_bild`` neu gezeichnet (ohne
Metadaten) und dann ausgeliefert wie jedes andere Bild eines Beitrags — erst
nach Freigabe, Verzögerung und Platzierung. Der Dienst sieht einen Abruf je
Link, keinen je Zuschauer.

Nur, wo der Dienst ein Vorschaubild ohne Anmeldung hergibt:

- **YouTube**: aus der Video-Kennung, ``i.ytimg.com`` (ohne API).
- **TikTok**: ``thumbnail_url`` aus dem öffentlichen oEmbed.
- **Instagram, Facebook**: keins. Meta hat ``thumbnail_url`` im November 2025
  aus seinem oEmbed genommen; die Seiten selbst abzugreifen hieße, gegen eine
  Anmeldesperre zu scrapen. Der Beitrag bleibt dann, wie er war: Symbol statt
  Bild.

Abgerufen werden nur feste Hosts (``_HOSTS``), nur über https und ohne
Weiterleitungen — eine Adresse aus der oEmbed-Antwort ist fremdbestimmt, und
ohne diese Liste wäre das ein Weg, den Server beliebige Adressen ansprechen zu
lassen. Jeder Fehler heißt: keine Vorschau. Der Link-Beitrag entsteht trotzdem.
"""
import json
import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

from app.config import settings
from app.services import aktionsseite_bild
from app.services.aktionsseite_link import Link

logger = logging.getLogger(__name__)

# Ein Vorschaubild ist ein paar hundert KB; was darüber liegt, ist keins.
MAX_BYTES = 5 * 1024 * 1024
MAX_JSON = 64 * 1024
# Abgerufen wird im Durchgang des Telegram-Abholers: lieber ohne Vorschau als
# eine Gruppe, deren Nachrichten warten.
TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=3.0, pool=3.0)
# Nur in Tests gesetzt (``httpx.MockTransport``).
transport: httpx.AsyncBaseTransport | None = None

# Dienst → Hosts, von denen ein Bild kommen darf. Eine Subdomain zählt mit.
_HOSTS: dict[str, tuple[str, ...]] = {
    "youtube": ("i.ytimg.com",),
    "tiktok": ("tiktokcdn.com", "tiktokcdn-us.com", "tiktokcdn-eu.com"),
}
_TIKTOK_OEMBED = "https://www.tiktok.com/oembed"
_YT_KENNUNG = re.compile(r"[A-Za-z0-9_-]{11}")


class _Keine(Exception):
    """Keine Vorschau — der Grund steht im Log, sonst nirgends."""


def youtube_kennung(url: str) -> str | None:
    """Die Video-Kennung aus einer bereinigten YouTube-Adresse."""
    teile = urlsplit(url)
    host = (teile.hostname or "").lower()
    pfad = [s for s in teile.path.split("/") if s]
    kandidat = None
    if host == "youtu.be" and pfad:
        kandidat = pfad[0]
    elif pfad[:1] == ["watch"]:
        kandidat = dict(parse_qsl(teile.query)).get("v")
    elif len(pfad) >= 2 and pfad[0] in ("shorts", "live", "embed"):
        kandidat = pfad[1]
    return kandidat if kandidat and _YT_KENNUNG.fullmatch(kandidat) else None


def _erlaubt(url: str, dienst: str) -> bool:
    try:
        teile = urlsplit(url)
        port = teile.port
    except ValueError:
        return False
    host = (teile.hostname or "").lower().rstrip(".")
    if teile.scheme != "https" or port is not None or teile.username or teile.password:
        return False
    return any(host == d or host.endswith("." + d) for d in _HOSTS.get(dienst, ()))


async def _holen(client: httpx.AsyncClient, url: str, grenze: int) -> tuple[str, bytes]:
    async with client.stream("GET", url) as r:
        if r.status_code != 200:
            raise _Keine(f"HTTP {r.status_code}")
        daten = bytearray()
        async for stueck in r.aiter_bytes():
            daten += stueck
            if len(daten) > grenze:
                raise _Keine("zu groß")
        return r.headers.get("content-type", "").split(";")[0].strip().lower(), bytes(daten)


async def _youtube(client: httpx.AsyncClient, link: Link) -> bytes:
    kennung = youtube_kennung(link.url)
    if kennung is None:
        raise _Keine("keine Video-Kennung")
    # maxresdefault gibt es nicht für jedes Video; hqdefault immer.
    for name in ("maxresdefault", "hqdefault"):
        try:
            _, daten = await _holen(client, f"https://i.ytimg.com/vi/{kennung}/{name}.jpg", MAX_BYTES)
            return daten
        except _Keine:
            continue
    raise _Keine("kein Vorschaubild bei YouTube")


async def _tiktok(client: httpx.AsyncClient, link: Link) -> bytes:
    typ, roh = await _holen(client, f"{_TIKTOK_OEMBED}?{urlencode({'url': link.url})}", MAX_JSON)
    if typ != "application/json":
        raise _Keine(f"oEmbed liefert {typ or 'nichts'}")
    try:
        bild = json.loads(roh).get("thumbnail_url")
    except (ValueError, AttributeError) as e:
        raise _Keine("oEmbed ist kein JSON-Objekt") from e
    if not isinstance(bild, str) or not _erlaubt(bild, "tiktok"):
        raise _Keine("Vorschaubild von unbekanntem Host")
    _, daten = await _holen(client, bild, MAX_BYTES)
    return daten


_ABRUF = {"youtube": _youtube, "tiktok": _tiktok}


async def holen(link: Link) -> aktionsseite_bild.Bild | None:
    """Das Vorschaubild eines Links, fertig verarbeitet — oder ``None``."""
    abruf = _ABRUF.get(link.dienst)
    if abruf is None or not settings.link_vorschau_enabled:
        return None
    try:
        async with httpx.AsyncClient(
            transport=transport, timeout=TIMEOUT, follow_redirects=False,
            headers={"User-Agent": "ConvoyPlan-Aktionsseite (Vorschaubild)"},
        ) as client:
            daten = await abruf(client, link)
        return aktionsseite_bild.verarbeiten(daten)
    except (_Keine, aktionsseite_bild.BildFehler) as e:
        logger.info("Vorschau für %s: keine (%s)", link.dienst, e)
    except httpx.HTTPError as e:
        # Ohne die Adresse: Sie stammt aus der Gruppe.
        logger.info("Vorschau für %s: keine (%s)", link.dienst, type(e).__name__)
    return None
