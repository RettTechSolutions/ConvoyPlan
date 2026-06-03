from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superadmin
from app.config import settings
from app.database import get_db
from app.middleware.license_guard import reset_license_cache
from app.models.user import User
from app.services import audit
from app.services.instance import get_or_create_instance_id, get_saved_license_key, save_license_key
from app.services.license import validate_license

router = APIRouter(prefix="/license", tags=["license"])


@router.get("/instance-id")
async def get_instance_id(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Return the installation's machine fingerprint used for license binding."""
    instance_id = await get_or_create_instance_id(db)
    return {"instance_id": instance_id}


@router.get("/status")
async def license_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    instance_id = await get_or_create_instance_id(db)
    license_key = settings.license_key
    key_source = "env"
    if not license_key:
        license_key = await get_saved_license_key(db)
        key_source = "db"

    info = validate_license(license_key, instance_id)
    return {
        "valid": info.valid,
        "demo_mode": not info.valid,
        "license_id": info.license_id,
        "customer": info.customer,
        "email": info.email,
        "issued": info.issued,
        "expires": info.expires,
        "max_users": info.max_users,
        "instance_id": instance_id,
        "key_source": key_source,
        "error": info.error if not info.valid else None,
    }


class LicenseActivateRequest(BaseModel):
    license_key: str


@router.post("/activate")
async def activate_license(
    data: LicenseActivateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    """Validate and store a license key. Resets the middleware cache."""
    instance_id = await get_or_create_instance_id(db)
    info = validate_license(data.license_key.strip(), instance_id)

    if not info.valid:
        raise HTTPException(status_code=422, detail=info.error)

    await save_license_key(db, data.license_key.strip())
    reset_license_cache()
    await audit.record(
        db, audit.LICENSE_ACTIVATED, request=request, actor_id=current.id,
        actor_email=current.email, detail={"license_id": info.license_id, "customer": info.customer},
    )

    return {
        "valid": True,
        "demo_mode": False,
        "license_id": info.license_id,
        "customer": info.customer,
        "email": info.email,
        "issued": info.issued,
        "expires": info.expires,
        "max_users": info.max_users,
        "instance_id": instance_id,
        "key_source": "db",
        "error": None,
    }


@router.delete("/")
async def remove_license(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Remove the stored license key, reverting to demo mode."""
    await save_license_key(db, "")
    reset_license_cache()
    return {"demo_mode": True}


@router.get("/mode")
async def license_mode(db: AsyncSession = Depends(get_db)):
    """Public endpoint — no auth required.

    Returns only {demo_mode: bool} so any logged-in frontend client can show
    a banner without exposing instance IDs or license details.
    """
    license_key = settings.license_key
    if not license_key:
        license_key = await get_saved_license_key(db)
    instance_id = await get_or_create_instance_id(db)
    info = validate_license(license_key, instance_id)
    return {"demo_mode": not info.valid}
