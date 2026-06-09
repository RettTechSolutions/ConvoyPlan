import asyncio
import logging
import xml.etree.ElementTree as _ET
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

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
# SVG elements and attribute patterns that enable XSS
_SVG_BLOCKED_TAGS = {"script", "foreignobject"}


def _validate_image_content(content: bytes, ext: str) -> None:
    if ext == ".png" and not content[:8] == _PNG_MAGIC:
        raise HTTPException(400, "File content does not match PNG format")
    if ext in {".jpg", ".jpeg"} and not content[:3] == _JPEG_MAGIC:
        raise HTTPException(400, "File content does not match JPEG format")
    if ext == ".svg":
        try:
            root = _ET.fromstring(content.decode("utf-8", errors="replace"))
        except _ET.ParseError:
            raise HTTPException(400, "SVG file is not valid XML")
        local_root = root.tag.split("}")[-1].lower() if "}" in root.tag else root.tag.lower()
        if local_root != "svg":
            raise HTTPException(400, "SVG file must have an <svg> root element")
        for elem in root.iter():
            local_tag = elem.tag.split("}")[-1].lower() if "}" in elem.tag else elem.tag.lower()
            if local_tag in _SVG_BLOCKED_TAGS:
                raise HTTPException(400, f"SVG contains disallowed element: <{local_tag}>")
            for attr in elem.attrib:
                local_attr = attr.split("}")[-1].lower() if "}" in attr else attr.lower()
                if local_attr.startswith("on"):
                    raise HTTPException(400, f"SVG contains disallowed event handler: {local_attr}")
                val = elem.attrib[attr].strip().lower()
                if local_attr in {"href", "src", "xlink:href", "action"} and val.startswith(
                    ("javascript:", "data:")
                ):
                    raise HTTPException(400, "SVG contains disallowed URI scheme")

# Keep in sync with alembic/versions/0011_branding_defaults.py _DEFAULTS
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
    _validate_image_content(content, ext)
    # Verify magic bytes so a renamed executable cannot bypass the extension check.
    _MAGIC: dict[str, list[bytes]] = {
        ".png": [b"\x89PNG"],
        ".jpg": [b"\xff\xd8\xff"],
        ".jpeg": [b"\xff\xd8\xff"],
    }
    if ext in _MAGIC and not any(content.startswith(sig) for sig in _MAGIC[ext]):
        raise HTTPException(status_code=400, detail="File content does not match the declared type")
    LOGOS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{slot}{ext}"
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, (LOGOS_DIR / filename).write_bytes, content)
    await _upsert(db, f"branding.logo_{slot}", filename)
    await db.commit()
    return await _get_branding_response(db)
