"""Adresssuche (Geocoding) über HERE Geocoding & Search — mit Photon-Fallback.

Die Adresssuche im Plan-Editor tippt während der Eingabe (Autocomplete). Ist ein
HERE-API-Key hinterlegt, läuft sie über **HERE Autosuggest** — serverseitig
proxied, damit der Key **nie im Browser** landet. Ohne Key (oder wenn HERE
ausfällt) fällt der Dienst automatisch auf das offene, schlüssellose
**Photon (komoot)** zurück, sodass die Suche immer funktioniert.

HERE gibt EINEN Key für alle Produkte aus. Ist kein eigener ``HERE_API_KEY``
gesetzt, wird deshalb der HERE-Traffic-Key (ENV oder Admin-Panel) mitbenutzt —
der Key muss also nur an einer Stelle hinterlegt werden.
"""
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services import traffic_flow

logger = logging.getLogger(__name__)

_HEADERS = {"Accept": "application/json", "User-Agent": "ConvoyPlan/1.0"}

HERE_AUTOSUGGEST_URL = "https://autosuggest.search.hereapi.com/v1/autosuggest"
PHOTON_URL = "https://photon.komoot.io/api/"

# Soft-Bias auf die Mitte Deutschlands, damit deutsche Treffer vorne stehen
# (kein harter Filter — grenznahe Adressen bleiben auffindbar).
BIAS_LAT = 51.1657
BIAS_LON = 10.4515

MIN_QUERY_LEN = 2
_TIMEOUT = 8.0


def _compose(primary: str, postcode: str | None, place: str | None,
             state: str | None, country: str | None) -> dict | None:
    """Aus Adressbestandteilen ein {primary, secondary}-Paar bauen."""
    primary = (primary or "").strip()
    if not primary:
        return None
    # PLZ + Ort auf einer Zeile ("10115 Berlin"). Bei Stadtstaaten fällt das
    # redundante Bundesland (= Ort) weg, sonst stünde "Berlin, Berlin".
    city_line = " ".join(p for p in (postcode, place) if p)
    if state and state == place:
        state = None
    seen: set[str] = set()
    parts: list[str] = []
    for part in (city_line, state, country):
        if part and part != primary and part not in seen:
            seen.add(part)
            parts.append(part)
    return {"primary": primary, "secondary": ", ".join(parts)}


# ── HERE Autosuggest ─────────────────────────────────────────────────


def _here_results(data: dict) -> list[dict]:
    out: list[dict] = []
    for item in data.get("items", []):
        pos = item.get("position") or {}
        lat, lon = pos.get("lat"), pos.get("lng")
        if lat is None or lon is None:
            # Kategorie-/Ketten-Vorschläge ohne Position überspringen.
            continue
        addr = item.get("address") or {}
        street = addr.get("street")
        housenumber = addr.get("houseNumber")
        street_line = f"{street} {housenumber}".strip() if street else ""
        # Für POIs/Orte ohne Straße den Titel (erstes Segment) als Primärzeile.
        title_head = (item.get("title") or "").split(",")[0].strip()
        place = addr.get("city") or addr.get("district") or addr.get("county")
        primary = street_line or title_head or place or "Unbenannter Ort"
        composed = _compose(
            primary, addr.get("postalCode"), place,
            addr.get("state"), addr.get("countryName"),
        )
        if composed:
            out.append({"lat": lat, "lon": lon, **composed})
    return out


async def _here_search(client: httpx.AsyncClient, api_key: str, q: str, limit: int) -> list[dict]:
    resp = await client.get(HERE_AUTOSUGGEST_URL, params={
        "q": q,
        "at": f"{BIAS_LAT},{BIAS_LON}",
        "lang": "de",
        "limit": limit,
        "apiKey": api_key,
    })
    resp.raise_for_status()
    return _here_results(resp.json())


# ── Photon (komoot) — schlüsselloser Fallback ────────────────────────


def _photon_results(data: dict) -> list[dict]:
    out: list[dict] = []
    for feat in data.get("features", []):
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        p = feat.get("properties") or {}
        place = p.get("city") or p.get("town") or p.get("village") or p.get("county")
        street = p.get("street")
        housenumber = p.get("housenumber")
        street_line = f"{street} {housenumber}".strip() if street else ""
        primary = street_line or p.get("name") or place or "Unbenannter Ort"
        composed = _compose(
            primary, p.get("postcode"), place, p.get("state"), p.get("country"),
        )
        if composed:
            out.append({"lat": coords[1], "lon": coords[0], **composed})
    return out


async def _photon_search(client: httpx.AsyncClient, q: str, limit: int) -> list[dict]:
    resp = await client.get(PHOTON_URL, params={
        "q": q,
        "lang": "de",
        "limit": limit,
        "lat": BIAS_LAT,
        "lon": BIAS_LON,
    })
    resp.raise_for_status()
    return _photon_results(resp.json())


# ── Konfigurationsauflösung ──────────────────────────────────────────


async def resolve_here_key(db: AsyncSession) -> str:
    """Effektiver HERE-Key für die Adresssuche.

    Vorrang hat ein eigens gesetzter ``HERE_API_KEY``. Sonst wird der
    HERE-Traffic-Key mitbenutzt (ENV oder Admin-Panel), da HERE einen Key für
    alle Produkte ausgibt — so muss der Key nur an einer Stelle hinterlegt sein.
    """
    if settings.here_api_key.strip():
        return settings.here_api_key.strip()
    return (await traffic_flow.resolve_config(db)).here_key


# ── Öffentliche API ──────────────────────────────────────────────────


async def search(query: str, here_key: str, limit: int = 6) -> dict:
    """Adressen zu *query* suchen. HERE bevorzugt, Photon als Fallback."""
    q = (query or "").strip()
    if len(q) < MIN_QUERY_LEN:
        return {"provider": None, "results": []}

    limit = max(1, min(limit, 10))
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
        if here_key:
            try:
                return {"provider": "here", "results": await _here_search(client, here_key, q, limit)}
            except Exception as exc:
                # HERE nicht erreichbar/abgelehnt → transparenter Photon-Fallback.
                logger.warning("HERE geocoding failed, falling back to Photon: %s", exc)
        try:
            return {"provider": "photon", "results": await _photon_search(client, q, limit)}
        except Exception as exc:
            logger.error("Photon geocoding failed: %s", exc)
            raise
