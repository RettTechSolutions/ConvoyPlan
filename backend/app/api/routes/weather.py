import logging

from fastapi import APIRouter, HTTPException, Query

from app.services import weather as weather_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/weather", tags=["weather"])


@router.get("/")
async def get_weather(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    try:
        return await weather_svc.get_weather(lat, lon)
    except Exception as exc:
        logger.error("Weather request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Wetterdaten nicht verfügbar")
