import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.settings import SystemSetting
from app.models.user import User
from app.schemas.branding import BrandingResponse, BrandingUpdate

router = APIRouter(prefix="/branding", tags=["branding"])
logger = logging.getLogger(__name__)

BRANDING_DEFAULTS: dict[str, str] = {
    "branding.app_name": "ConvoyPlan",
    "branding.logo_main": "",
    "branding.logo_horizontal": "",
    "branding.color_primary": "#E23D28",
    "branding.color_primary_hover": "#C23020",
    "branding.color_accent": "#3498db",
    "branding.color_bg": "#f5f3ee",
    "branding.color_surface": "#ffffff",
    "branding.color_nav_bg": "#2c3e50",
    "branding.color_nav_text": "#ecf0f1",
    "branding.color_text": "#2c3e50",
    "branding.color_text_muted": "#7f8c8d",
}

LOGOS_DIR = Path("/uploads/logos")


async def _get_branding_response(db: AsyncSession) -> BrandingResponse:
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key.like("branding.%"))
    )
    stored = {s.key: s.value for s in result.scalars().all()}
    merged: dict[str, str] = {**BRANDING_DEFAULTS, **stored}
    logo_main = merged["branding.logo_main"]
    logo_horizontal = merged["branding.logo_horizontal"]
    return BrandingResponse(
        app_name=merged["branding.app_name"],
        logo_main_url=f"/uploads/logos/{logo_main}" if logo_main else None,
        logo_horizontal_url=f"/uploads/logos/{logo_horizontal}" if logo_horizontal else None,
        color_primary=merged["branding.color_primary"],
        color_primary_hover=merged["branding.color_primary_hover"],
        color_accent=merged["branding.color_accent"],
        color_bg=merged["branding.color_bg"],
        color_surface=merged["branding.color_surface"],
        color_nav_bg=merged["branding.color_nav_bg"],
        color_nav_text=merged["branding.color_nav_text"],
        color_text=merged["branding.color_text"],
        color_text_muted=merged["branding.color_text_muted"],
    )


async def _upsert(db: AsyncSession, key: str, value: str) -> None:
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        db.add(SystemSetting(key=key, value=value))


@router.get("", response_model=BrandingResponse)
async def get_branding(db: AsyncSession = Depends(get_db)):
    return await _get_branding_response(db)


@router.put("", response_model=BrandingResponse)
async def update_branding(
    data: BrandingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BrandingResponse:
    if not current_user.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmin required")
    updates = {
        "branding.app_name": data.app_name,
        "branding.color_primary": data.color_primary,
        "branding.color_primary_hover": data.color_primary_hover,
        "branding.color_accent": data.color_accent,
        "branding.color_bg": data.color_bg,
        "branding.color_surface": data.color_surface,
        "branding.color_nav_bg": data.color_nav_bg,
        "branding.color_nav_text": data.color_nav_text,
        "branding.color_text": data.color_text,
        "branding.color_text_muted": data.color_text_muted,
    }
    for key, value in updates.items():
        await _upsert(db, key, value)
    await db.commit()
    return await _get_branding_response(db)


@router.post("/logo/{slot}", response_model=BrandingResponse)
async def upload_logo(
    slot: Literal["main", "horizontal"],
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BrandingResponse:
    if not current_user.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmin required")
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 2 MB)")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".svg"}:
        raise HTTPException(status_code=400, detail="Invalid file type (PNG, JPG, SVG only)")
    LOGOS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{slot}{ext}"
    (LOGOS_DIR / filename).write_bytes(content)
    await _upsert(db, f"branding.logo_{slot}", filename)
    await db.commit()
    return await _get_branding_response(db)
