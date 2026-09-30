"""Kacheln für die Karte — über die eigene Instanz statt direkt beim Kachelserver.

Ohne Anmeldung erreichbar: Auch die Karte am Tracking-Link braucht Kacheln, und
dort ist niemand angemeldet. Damit die Instanz kein offener Gratis-Proxy wird,
sind Zoomstufe und Koordinaten geprüft und die Abrufe je Client-IP begrenzt.
Einzelheiten zum Cache: ``app.services.tile_proxy``.
"""

from fastapi import APIRouter, HTTPException, Request, Response

from app.config import settings
from app.services import rate_limit, tile_proxy
from app.services.audit import client_ip

router = APIRouter(prefix="/tiles", tags=["tiles"])

# Browser und Service Worker dürfen eine Kachel eine Woche behalten; der
# Service Worker frischt sie ohnehin im Hintergrund auf (StaleWhileRevalidate).
_CACHE_CONTROL = "public, max-age=604800"


@router.get("/config")
async def tile_config():
    """Woher die Karte ihre Kacheln lädt und wie viel sie vorab laden darf."""
    return {
        "url": "/api/tiles/{z}/{x}/{y}.png",
        "prefetch": tile_proxy.prefetch_profile(),
    }


@router.get("/{z}/{x}/{y}.png")
async def get_tile(z: int, x: int, y: int, request: Request):
    if settings.rate_limit_enabled:
        wait = rate_limit.check(
            f"tiles:{client_ip(request) or 'unbekannt'}",
            settings.tile_rate_limit_per_minute, 60, record=True,
        )
        if wait is not None:
            raise rate_limit.too_many_requests(wait)
    if not tile_proxy.valid(z, x, y):
        raise HTTPException(status_code=404, detail="Keine solche Kachel")
    try:
        data = await tile_proxy.get_tile(z, x, y)
    except tile_proxy.TileUnavailable:
        raise HTTPException(
            status_code=502,
            detail="Kachel derzeit nicht verfügbar",
            headers={"Cache-Control": "no-store"},
        )
    return Response(
        content=data,
        media_type=tile_proxy.media_type(data),
        headers={"Cache-Control": _CACHE_CONTROL},
    )
