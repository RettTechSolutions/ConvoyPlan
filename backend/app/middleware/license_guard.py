"""
Middleware that enforces a valid license.

Without a valid license the app runs in demo mode:
  - GET requests are always allowed (read-only access)
  - Mutating requests (POST/PUT/PATCH/DELETE) on protected endpoints
    return HTTP 402 with a clear message

The license key is resolved in order:
  1. LICENSE_KEY environment variable / .env
  2. system_settings table row  "license.key"

The result is cached for the lifetime of the process.
Call reset_license_cache() after saving a new key via the API.

Exempt paths (always allowed regardless of method):
  - /health
  - /api/auth/login
  - /api/license/*
  - /api/setup/*
  - /uploads/*
  - /docs, /redoc, /openapi.json
"""
import asyncio

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.database import AsyncSessionLocal
from app.services.instance import get_or_create_instance_id, get_saved_license_key
from app.services.license import validate_license

_EXEMPT_PREFIXES = (
    "/health",
    "/api/auth/login",
    "/api/license/",
    "/api/setup",
    "/api/track/",
    "/api/ws/track/",
    "/uploads",
    "/docs",
    "/redoc",
    "/openapi.json",
)

_license_valid: bool | None = None
_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def reset_license_cache() -> None:
    global _license_valid
    _license_valid = None


async def _check_license() -> bool:
    global _license_valid
    if _license_valid is not None:
        return _license_valid

    async with _get_lock():
        if _license_valid is not None:
            return _license_valid

        license_key = settings.license_key

        if not license_key:
            try:
                async with AsyncSessionLocal() as db:
                    license_key = await get_saved_license_key(db)
            except Exception:
                license_key = ""

        try:
            async with AsyncSessionLocal() as db:
                instance_id = await get_or_create_instance_id(db)
        except Exception:
            instance_id = ""

        _license_valid = validate_license(license_key, instance_id).valid

    return _license_valid


class LicenseGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        if await _check_license():
            return await call_next(request)

        # Demo mode: allow reads, block writes
        if request.method == "GET":
            return await call_next(request)

        return JSONResponse(
            status_code=402,
            content={
                "detail": "Demo-Modus aktiv. Bitte geben Sie einen gültigen Lizenzschlüssel ein.",
                "demo_mode": True,
            },
        )
