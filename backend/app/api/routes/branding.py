import asyncio
import json
import logging
import re
import defusedxml.ElementTree as _ET
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.organization import Organization
from app.models.settings import SystemSetting
from app.models.user import User
from app.schemas.branding import BrandingResponse, BrandingUpdate

router = APIRouter(prefix="/branding", tags=["branding"])
logger = logging.getLogger(__name__)

_MAGIC_PNG = b"\x89PNG\r\n\x1a\n"
_MAGIC_JPEG = b"\xff\xd8\xff"
_SVG_BLOCKED_TAGS = {"script", "foreignobject"}
# Quick pre-filter: catches the most common SVG XSS patterns before XML parsing.
_SVG_ACTIVE_CONTENT = re.compile(
    rb"<script|javascript:|on(?:load|error|click|mouse\w+|key\w+|submit|focus|blur)\s*=",
    re.IGNORECASE,
)


def _validate_image_content(content: bytes, ext: str) -> None:
    """Raise HTTP 400 if the bytes do not match the declared extension or contain active content."""
    if ext == ".png" and not content.startswith(_MAGIC_PNG):
        raise HTTPException(status_code=400, detail="File content does not match declared type (expected PNG)")
    if ext in {".jpg", ".jpeg"} and not content.startswith(_MAGIC_JPEG):
        raise HTTPException(status_code=400, detail="File content does not match declared type (expected JPEG)")
    if ext == ".svg":
        # Quick regex pre-filter for common XSS patterns.
        if _SVG_ACTIVE_CONTENT.search(content):
            raise HTTPException(status_code=400, detail="SVG files must not contain scripts or event handlers")
        # Full XML structural check to catch vectors the regex misses:
        # <foreignObject> content injection, data:/javascript: URIs in href/src,
        # and event-handler attributes not covered by the regex (ondrag*, onpointer*, etc.)
        try:
            root = _ET.fromstring(content.decode("utf-8", errors="replace"))
        except _ET.ParseError:
            raise HTTPException(status_code=400, detail="SVG file is not valid XML")
        local_root = root.tag.split("}")[-1].lower() if "}" in root.tag else root.tag.lower()
        if local_root != "svg":
            raise HTTPException(status_code=400, detail="SVG file must have an <svg> root element")
        for elem in root.iter():
            local_tag = elem.tag.split("}")[-1].lower() if "}" in elem.tag else elem.tag.lower()
            if local_tag in _SVG_BLOCKED_TAGS:
                raise HTTPException(status_code=400, detail=f"SVG contains disallowed element: <{local_tag}>")
            for attr in elem.attrib:
                local_attr = attr.split("}")[-1].lower() if "}" in attr else attr.lower()
                if local_attr.startswith("on"):
                    raise HTTPException(status_code=400, detail=f"SVG contains disallowed event handler: {local_attr}")
                val = elem.attrib[attr].strip().lower()
                if local_attr in {"href", "src", "xlink:href", "action"} and val.startswith(
                    ("javascript:", "data:")
                ):
                    raise HTTPException(status_code=400, detail="SVG contains disallowed URI scheme")

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

# Ausgeliefert werden die Logos über die API und nicht über einen statischen
# Mount unter /uploads: Caddy reicht nur /api/* ans Backend durch, alles andere
# geht ans Frontend. /uploads/logos/… landete dort im 404 — für jedes Logo,
# nicht nur für SVG, und der Upload selbst meldete trotzdem Erfolg.
LOGO_URL_PREFIX = "/api/branding/logos/"
_LOGO_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
}
# Nur, was die Upload-Endpunkte selbst erzeugen (`main.png`, `org-<uuid>-horizontal.svg`).
# Kein Punkt vor der Endung, kein Schrägstrich — damit führt kein Name aus LOGOS_DIR hinaus.
_LOGO_NAME = re.compile(r"^[A-Za-z0-9_-]+\.(?:png|jpe?g|svg)$")
# Ein direkt geöffnetes SVG ist ein Dokument dieser Origin. Die Upload-Prüfung
# lässt kein Skript durch; die Sandbox ist die zweite Tür, falls sie etwas übersieht.
_SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'; sandbox"


def logo_url(filename: str) -> str | None:
    """Öffentliche URL eines Logos, mit Änderungszeit als Cache-Brecher.

    Der Dateiname bleibt beim Ersetzen gleich (`org-<id>-horizontal.svg`); ohne
    `?v=` zeigte der Browser nach einem neuen Upload das alte Bild aus dem Cache.
    """
    if not filename:
        return None
    try:
        version = f"?v={int((LOGOS_DIR / filename).stat().st_mtime)}"
    except OSError:
        version = ""
    return f"{LOGO_URL_PREFIX}{filename}{version}"

async def _global_branding_dict(db: AsyncSession) -> dict[str, str]:
    """Platform-wide branding: defaults overlaid with SystemSetting values."""
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key.like("branding.%"))
    )
    stored = {s.key: s.value for s in result.scalars().all()}
    return {**BRANDING_DEFAULTS, **stored}


def org_branding_overrides(org: Organization) -> dict[str, str]:
    """Parse the org's branding JSON; empty dict if unset or malformed."""
    if not org.branding:
        return {}
    try:
        data = json.loads(org.branding)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)}


async def org_branding_response(db: AsyncSession, org: Organization) -> BrandingResponse:
    """Effective branding for an org: platform branding + org overrides on top."""
    merged = await _global_branding_dict(db)
    for key, value in org_branding_overrides(org).items():
        merged[f"branding.{key}"] = value
    return _branding_response_from(merged)


def _branding_response_from(merged: dict[str, str]) -> BrandingResponse:
    logo_main = merged["branding.logo_main"]
    logo_horizontal = merged["branding.logo_horizontal"]
    return BrandingResponse(
        app_name=merged["branding.app_name"],
        logo_main_url=logo_url(logo_main),
        logo_horizontal_url=logo_url(logo_horizontal),
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


async def _get_branding_response(db: AsyncSession) -> BrandingResponse:
    return _branding_response_from(await _global_branding_dict(db))


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


@router.get("/logos/{filename}")
async def get_logo(filename: str) -> FileResponse:
    """Public like GET /branding: the login page shows the logo before anyone signs in."""
    if not _LOGO_NAME.fullmatch(filename):
        raise HTTPException(status_code=404, detail="Logo nicht gefunden")
    path = LOGOS_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Logo nicht gefunden")
    ext = path.suffix.lower()
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "public, max-age=86400",
    }
    if ext == ".svg":
        headers["Content-Security-Policy"] = _SVG_CSP
    return FileResponse(path, media_type=_LOGO_MEDIA_TYPES[ext], headers=headers)


@router.get("/org/{slug}", response_model=BrandingResponse)
async def get_org_branding_by_slug(slug: str, db: AsyncSession = Depends(get_db)):
    """Public: effective branding for one org (platform branding + org overrides).

    Like GET /branding this is unauthenticated so the org login page can already
    be themed; colors/names/logos are not secrets."""
    result = await db.execute(select(Organization).where(Organization.slug == slug))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden")
    return await org_branding_response(db, org)


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
    LOGOS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{slot}{ext}"
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, (LOGOS_DIR / filename).write_bytes, content)
    await _upsert(db, f"branding.logo_{slot}", filename)
    await db.commit()
    return await _get_branding_response(db)
