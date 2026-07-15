import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.services import geocoding as geo_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/geocode", tags=["geocode"])


@router.get("/search")
async def search_address(
    q: str = Query(..., min_length=geo_svc.MIN_QUERY_LEN, max_length=200),
    limit: int = Query(6, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Adresssuche (Autocomplete) über HERE, mit Photon-Fallback ohne Key.

    Der HERE-Key bleibt serverseitig — das Frontend fragt nur diesen Proxy an.
    Ein monatlicher HERE-Kostendeckel (``HERE_MONTHLY_LIMIT``) schaltet nach
    Erreichen des Budgets für den Rest des Monats auf Photon um, damit keine
    Kosten entstehen. Antwort: ``{"provider": "here"|"photon"|null, "results":
    [{lat, lon, primary, secondary}, ...]}``.
    """
    try:
        here_key = await geo_svc.resolve_here_key(db)
        # Vor dem HERE-Aufruf das Monatsbudget verbuchen. Ist der Deckel
        # erreicht, den Key fallen lassen → search() nutzt dann Photon.
        if here_key and settings.here_monthly_limit > 0:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            if not await geo_svc.reserve_here_quota(db, month, settings.here_monthly_limit):
                here_key = ""
        return await geo_svc.search(q, here_key, limit)
    except Exception as exc:
        logger.error("Address search failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Adresssuche nicht verfügbar")
