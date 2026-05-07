from datetime import datetime, timezone

import httpx
from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.config import settings
from app.database import get_db
from app.services import weather as weather_svc
from app.services import overpass as overpass_svc

router = APIRouter(prefix="/status", tags=["status"])


@router.get("")
async def service_status(db: AsyncSession = Depends(get_db)):
    # Database
    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    # GraphHopper
    gh_status = "offline"
    gh_bbox = None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            h = await client.get(f"{settings.graphhopper_url}/health")
            if h.is_success:
                gh_status = "ok"
                info = await client.get(f"{settings.graphhopper_url}/info")
                if info.is_success:
                    data = info.json()
                    gh_bbox = data.get("bbox")
            else:
                gh_status = "building"
    except (httpx.ConnectError, httpx.ConnectTimeout):
        # Host unreachable — container is down
        gh_status = "offline"
    except Exception:
        # ReadTimeout / other — GH is up but still importing graph
        gh_status = "building"

    overpass_check = await overpass_svc.probe()

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "backend": "ok",
        "database": "ok" if db_ok else "error",
        "graphhopper": gh_status,
        "graphhopper_bbox": gh_bbox,
        "weather_api": weather_svc.last_check(),
        "overpass_api": overpass_check,
    }
