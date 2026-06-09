import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.services import overpass as overpass_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/overpass", tags=["overpass"])


@router.get("/closures")
async def get_closures(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_m: int = Query(15000, ge=1000, le=50000),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        return await overpass_svc.get_closures(lat, lon, radius_m)
    except Exception as exc:
        logger.warning("Overpass query failed: %s", exc)
        logger.error("Overpass closures fetch failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Sperrungsdaten nicht verfügbar")
