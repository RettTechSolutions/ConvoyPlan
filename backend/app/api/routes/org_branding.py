"""Org-scoped branding management.

Org admins customize branding (app name, colors, logos) for their own
organization only. The overrides are stored as JSON on the organization row
and are layered on top of the platform branding (SystemSetting `branding.*`),
which remains superadmin-only via /branding.
"""
import asyncio
import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OrgCtx, get_org_context
from app.api.guards import ROLE_ORDER
from app.database import get_db
from app.api.routes.branding import (
    LOGOS_DIR,
    _validate_image_content,
    org_branding_overrides,
    org_branding_response,
)
from app.schemas.branding import BrandingResponse, BrandingUpdate

router = APIRouter(prefix="/org/branding", tags=["branding"])


def _require_admin(role: str) -> None:
    if ROLE_ORDER.get(role, -1) < ROLE_ORDER["admin"]:
        raise HTTPException(status_code=403, detail="Org-Adminrechte erforderlich")


def _delete_org_logos(org_id) -> None:
    for path in LOGOS_DIR.glob(f"org-{org_id}-*"):
        try:
            path.unlink()
        except OSError:
            pass


@router.get("", response_model=BrandingResponse)
async def get_org_branding(
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    _, org, _role = ctx
    return await org_branding_response(db, org)


@router.put("", response_model=BrandingResponse)
async def update_org_branding(
    data: BrandingUpdate,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
) -> BrandingResponse:
    _, org, role = ctx
    _require_admin(role)
    overrides = data.model_dump()
    # Logo overrides are managed via the upload endpoint — carry them over.
    current = org_branding_overrides(org)
    for slot in ("logo_main", "logo_horizontal"):
        if slot in current:
            overrides[slot] = current[slot]
    org.branding = json.dumps(overrides)
    await db.commit()
    return await org_branding_response(db, org)


@router.post("/logo/{slot}", response_model=BrandingResponse)
async def upload_org_logo(
    slot: Literal["main", "horizontal"],
    file: UploadFile = File(...),
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
) -> BrandingResponse:
    _, org, role = ctx
    _require_admin(role)
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 2 MB)")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".svg"}:
        raise HTTPException(status_code=400, detail="Invalid file type (PNG, JPG, SVG only)")
    _validate_image_content(content, ext)
    LOGOS_DIR.mkdir(parents=True, exist_ok=True)
    # Namespaced per org so org uploads can never clobber the platform logos
    # (main.png etc.) or another org's files.
    filename = f"org-{org.id}-{slot}{ext}"
    overrides = org_branding_overrides(org)
    old = overrides.get(f"logo_{slot}")
    if old and old != filename and old.startswith(f"org-{org.id}-"):
        try:
            (LOGOS_DIR / old).unlink()
        except OSError:
            pass
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, (LOGOS_DIR / filename).write_bytes, content)
    overrides[f"logo_{slot}"] = filename
    org.branding = json.dumps(overrides)
    await db.commit()
    return await org_branding_response(db, org)


@router.delete("", response_model=BrandingResponse)
async def reset_org_branding(
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
) -> BrandingResponse:
    """Remove all org overrides — the org falls back to the platform branding."""
    _, org, role = ctx
    _require_admin(role)
    _delete_org_logos(org.id)
    org.branding = None
    await db.commit()
    return await org_branding_response(db, org)
