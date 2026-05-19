"""
Middleware that enforces a valid license.

The instance_id is fetched from the DB on the first protected request and
cached for the lifetime of the process. A restart is required to pick up a
new LICENSE_KEY or a newly-created instance_id.

Exempt paths (always allowed):
  - /health
  - /api/auth/login  (so admins can log in to check the status)
  - /api/license/*   (instance-id + status endpoints)
  - /api/setup/*     (first-run setup must work)
  - /uploads/*       (static files)
  - /docs, /openapi.json
"""
import asyncio

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.database import AsyncSessionLocal
from app.services.instance import get_or_create_instance_id
from app.services.license import validate_license

_EXEMPT_PREFIXES = (
    "/health",
    "/api/auth/login",
    "/api/license/",
    "/api/setup",
    "/uploads",
    "/docs",
    "/openapi.json",
)

_lock = asyncio.Lock()
_license_valid: bool | None = None


async def _check_license() -> bool:
    global _license_valid
    if _license_valid is not None:
        return _license_valid

    async with _lock:
        if _license_valid is not None:
            return _license_valid

        try:
            async with AsyncSessionLocal() as db:
                instance_id = await get_or_create_instance_id(db)
        except Exception:
            instance_id = ""

        _license_valid = validate_license(settings.license_key, instance_id).valid

    return _license_valid


class LicenseGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        if not await _check_license():
            return JSONResponse(
                status_code=402,
                content={"detail": "No valid license. Contact your administrator."},
            )

        return await call_next(request)
