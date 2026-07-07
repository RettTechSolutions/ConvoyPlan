import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.services import overpass as overpass_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/overpass", tags=["overpass"])


class RouteClosuresRequest(BaseModel):
    """Route geometry in GeoJSON coordinate order: [[lon, lat], ...]."""

    coordinates: list[list[float]] = Field(..., min_length=2, max_length=25000)
    corridor_m: int = Field(2000, ge=100, le=10000)

    @field_validator("coordinates")
    @classmethod
    def _validate_coords(cls, v: list[list[float]]) -> list[list[float]]:
        for c in v:
            if len(c) < 2 or not (-180 <= c[0] <= 180) or not (-90 <= c[1] <= 90):
                raise ValueError("Ungültige Koordinate (erwartet [lon, lat])")
        return v


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
        logger.error("Overpass closures fetch failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Sperrungsdaten nicht verfügbar")


@router.post("/closures/route")
async def get_closures_for_route(
    body: RouteClosuresRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Sperrungen/Baustellen im Korridor entlang der gesamten Route."""
    coords = [(c[0], c[1]) for c in body.coordinates]
    try:
        return await overpass_svc.get_closures_along_route(coords, body.corridor_m)
    except Exception as exc:
        logger.error("Overpass route closures fetch failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Sperrungsdaten nicht verfügbar")
