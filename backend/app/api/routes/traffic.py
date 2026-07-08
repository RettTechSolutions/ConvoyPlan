import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.services import traffic_flow as flow_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/traffic", tags=["traffic"])


class RouteFlowRequest(BaseModel):
    """Route geometry in GeoJSON coordinate order: [[lon, lat], ...]."""

    coordinates: list[list[float]] = Field(..., min_length=2, max_length=25000)
    corridor_m: int = Field(1000, ge=100, le=5000)

    @field_validator("coordinates")
    @classmethod
    def _validate_coords(cls, v: list[list[float]]) -> list[list[float]]:
        for c in v:
            if len(c) < 2 or not (-180 <= c[0] <= 180) or not (-90 <= c[1] <= 90):
                raise ValueError("Ungültige Koordinate (erwartet [lon, lat])")
        return v


@router.get("/flow/status")
async def flow_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Welcher Live-Verkehrslage-Anbieter konfiguriert ist (oder keiner)."""
    cfg = await flow_svc.resolve_config(db)
    return {"provider": cfg.provider}


@router.get("/flow")
async def get_flow(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_m: int = Query(3000, ge=100, le=20000),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Live-Verkehrslage im Umkreis (leer, wenn kein Anbieter-Key gesetzt)."""
    try:
        cfg = await flow_svc.resolve_config(db)
        return await flow_svc.flow_around(lat, lon, cfg, radius_m)
    except Exception as exc:
        logger.error("Traffic flow fetch failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Verkehrslage nicht verfügbar")


@router.post("/flow/route")
async def get_flow_for_route(
    body: RouteFlowRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Live-Verkehrslage im Korridor entlang der Route (leer ohne Anbieter-Key)."""
    coords = [(c[0], c[1]) for c in body.coordinates]
    try:
        cfg = await flow_svc.resolve_config(db)
        return await flow_svc.flow_along_route(coords, cfg, body.corridor_m)
    except Exception as exc:
        logger.error("Traffic flow route fetch failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Verkehrslage nicht verfügbar")
