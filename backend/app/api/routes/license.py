from fastapi import APIRouter, Depends

from app.api.deps import require_superadmin
from app.config import settings
from app.models.user import User
from app.services.license import validate_license

router = APIRouter(tags=["license"])


@router.get("/license/status")
async def license_status(_: User = Depends(require_superadmin)):
    info = validate_license(settings.license_key)
    return {
        "valid": info.valid,
        "license_id": info.license_id,
        "customer": info.customer,
        "email": info.email,
        "issued": info.issued,
        "expires": info.expires,
        "max_users": info.max_users,
        "error": info.error if not info.valid else None,
    }
