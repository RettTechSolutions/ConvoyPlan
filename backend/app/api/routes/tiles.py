import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Path, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.services import smartmaps as smartmaps_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tiles", tags=["tiles"])

# YellowMap SmartMaps Raster Tile API (WebP). Der Kartenstil steht im Pfad
# ({style}), der Key als Query-Param apiKey. Siehe docs.smartmaps.cloud.
SMARTMAPS_TILE_URL = "https://tiles.smartmaps.cloud/tiles/v1/smartmaps/{style}/{z}/{x}/{y}.webp"
OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
_TIMEOUT = 8.0
_TILE_CACHE_MAX_AGE = 86400  # 1 Tag — Kacheln sind praktisch unveränderlich; senkt Backend-Last und Budgetverbrauch.


async def _proxy_osm(osm_url: str) -> Response:
    """Holt die OSM-Fallback-Kachel serverseitig und reicht sie same-origin durch.

    Same-origin-Proxy statt 302-Redirect, damit keine offene Weiterleitung auf
    eine aus Pfadsegmenten zusammengesetzte externe URL entsteht. Schlägt auch
    OSM fehl, degradiert der Endpoint still auf 502 (MapLibre zeigt dann eine
    leere Kachel) statt eine unbehandelte Exception (500) zu werfen.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            osm_resp = await client.get(osm_url)
            osm_resp.raise_for_status()
        return Response(
            content=osm_resp.content,
            media_type=osm_resp.headers.get("content-type", "image/png").split(";")[0],
            headers={"Cache-Control": f"public, max-age={_TILE_CACHE_MAX_AGE}"},
        )
    except Exception as exc:
        logger.warning("OSM-Fallback-Kachel-Abruf fehlgeschlagen: %s", exc)
        return Response(status_code=502)


@router.get("/smartmaps/{z}/{x}/{y}")
async def get_smartmaps_tile(
    z: int = Path(ge=0, le=22),
    x: int = Path(ge=0),
    y: int = Path(ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """SmartMaps-Kachel (YellowMap Raster Tile API, WebP), serverseitig proxied.

    Der SmartMaps-Key bleibt serverseitig — das Frontend fragt nur diesen Proxy
    an. Ein Jahresdeckel (``SMARTMAPS_YEARLY_LIMIT``) verbucht jede Anfrage im
    In-Memory-Zähler aus ``smartmaps.py`` und fällt bei erreichtem Deckel — wie
    auch bei fehlendem Key oder jedem SmartMaps-Fehler — auf die OSM-Kachel
    zurück.
    """
    osm_url = OSM_TILE_URL.format(z=z, x=x, y=y)

    api_key = settings.smartmaps_api_key.strip()
    if api_key and settings.smartmaps_yearly_limit > 0:
        year = datetime.now(timezone.utc).strftime("%Y")
        if not await smartmaps_svc.reserve_tile_quota(db, year, settings.smartmaps_yearly_limit):
            api_key = ""

    if not api_key:
        return await _proxy_osm(osm_url)

    tile_url = SMARTMAPS_TILE_URL.format(style=settings.smartmaps_style, z=z, x=x, y=y)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(tile_url, params={"apiKey": api_key})
            resp.raise_for_status()
            return Response(
                content=resp.content,
                media_type="image/webp",
                headers={"Cache-Control": f"public, max-age={_TILE_CACHE_MAX_AGE}"},
            )
    except Exception as exc:
        logger.warning("SmartMaps-Tile-Abruf fehlgeschlagen, Fallback auf OSM: %s", exc)
        return await _proxy_osm(osm_url)
