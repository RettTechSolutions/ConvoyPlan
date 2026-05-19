from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superadmin
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.services.instance import get_or_create_instance_id
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
    info = validate_license(settings.license_key, instance_id)
    return {
        "valid": info.valid,
        "license_id": info.license_id,
        "customer": info.customer,
        "email": info.email,
        "issued": info.issued,
        "expires": info.expires,
        "max_users": info.max_users,
        "instance_id": instance_id,
        "error": info.error if not info.valid else None,
    }
