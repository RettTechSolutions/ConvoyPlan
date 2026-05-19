"""
Middleware that enforces a valid license.

Exempt paths (always allowed):
  - /health
  - /api/auth/login  (so admins can log in to check the status)
  - /api/license/status  (so admins can see what's wrong)
  - /api/setup/*  (first-run setup must work)
  - /uploads/*  (static files)

All other requests get 402 when the license is invalid or missing.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.services.license import validate_license

_EXEMPT_PREFIXES = (
    "/health",
    "/api/auth/login",
    "/api/license/status",
    "/api/setup",
    "/uploads",
    "/docs",
    "/openapi.json",
)

# Cache result — invalidated only on restart (LICENSE_KEY / DOMAIN change requires restart).
_cached_valid: bool | None = None


def _is_licensed() -> bool:
    global _cached_valid
    if _cached_valid is None:
        _cached_valid = validate_license(settings.license_key, settings.domain).valid
    return _cached_valid


class LicenseGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        if not _is_licensed():
            return JSONResponse(
                status_code=402,
                content={"detail": "No valid license. Contact support to activate ConvoyPlan."},
            )

        return await call_next(request)
