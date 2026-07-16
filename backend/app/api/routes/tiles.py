import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.services import geocoding as geo_svc
from app.services import smartmaps as smartmaps_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tiles", tags=["tiles"])

HERE_TILE_URL = "https://maps.hereapi.com/v3/base/mc/{z}/{x}/{y}/png8"
OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
_TIMEOUT = 8.0


@router.get("/here/{z}/{x}/{y}")
async def get_here_tile(
    z: int,
    x: int,
    y: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """HERE-SmartMaps-Kachel (Raster Tile API v3), serverseitig proxied.

    Der HERE-Key bleibt serverseitig — das Frontend fragt nur diesen Proxy an.
    Ein Jahresdeckel (``HERE_SMARTMAPS_YEARLY_LIMIT``) verbucht jede Anfrage im
    In-Memory-Zähler aus ``smartmaps.py`` und fällt bei erreichtem Deckel —
    wie auch bei jedem HERE-Fehler — auf die OSM-Kachel zurück.
    """
    osm_url = OSM_TILE_URL.format(z=z, x=x, y=y)

    here_key = await geo_svc.resolve_here_key(db)
    if here_key and settings.here_smartmaps_yearly_limit > 0:
        year = datetime.now(timezone.utc).strftime("%Y")
        if not await smartmaps_svc.reserve_tile_quota(db, year, settings.here_smartmaps_yearly_limit):
            here_key = ""

    if not here_key:
        return RedirectResponse(url=osm_url, status_code=302)

    tile_url = HERE_TILE_URL.format(z=z, x=x, y=y)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(tile_url, params={"style": "explore.day", "apiKey": here_key})
            resp.raise_for_status()
            return Response(content=resp.content, media_type="image/png")
    except Exception as exc:
        logger.warning("HERE-Tile-Abruf fehlgeschlagen, Fallback auf OSM: %s", exc)
        return RedirectResponse(url=osm_url, status_code=302)
