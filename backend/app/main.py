import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import (
    auth, convoys, vehicles, routing, organizations,
    tracking, weather, overpass, status, users, leitstellen,
)
from app.api.routes import admin as admin_router
from app.api.routes import branding as branding_router
from app.api.routes import email_template as email_template_router
from app.api.routes import license as license_router
from app.api.routes import setup as setup_router
from app.api.routes import share_links as share_links_router
from app.api.routes import track as track_router
from app.api.routes import version as version_router
from app.config import settings
from app.middleware.license_guard import LicenseGuardMiddleware

logger = logging.getLogger(__name__)

_INSECURE_JWT_SECRETS = {"", "changeme-in-production", "change-me-generate-a-real-secret"}
_DEV_ENVS = {"dev", "development", "local", "test", "testing"}


def _verify_security_config() -> None:
    """Fail-closed: refuse to start in production with a weak JWT secret.

    Generate a strong value with `openssl rand -hex 32` and set JWT_SECRET.
    Relax for local work with APP_ENV=development.
    """
    if settings.app_env.lower() in _DEV_ENVS:
        return
    secret = settings.jwt_secret
    if secret in _INSECURE_JWT_SECRETS or len(secret) < 32:
        raise RuntimeError(
            "Insecure JWT_SECRET in production: set a strong secret of at least "
            "32 characters (e.g. `openssl rand -hex 32`) via the JWT_SECRET "
            "environment variable, or set APP_ENV=development for local use."
        )


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _verify_security_config()
    yield


app = FastAPI(title="ConvoyPlan API", version="0.5.0", lifespan=_lifespan)


def _resolve_cors_origins() -> list[str]:
    """Determine the allowed CORS origins.

    - explicit `CORS_ORIGINS` (comma list or "*") always wins;
    - otherwise in production we lock down to the app's own origin
      (frontend and API are same-origin behind Caddy, so this never breaks
      the UI while refusing a wildcard);
    - otherwise (development) we allow "*".
    """
    raw = settings.cors_origins.strip()
    if raw:
        if raw == "*":
            if settings.app_env.lower() not in _DEV_ENVS:
                logger.warning(
                    "CORS_ORIGINS='*' in production is discouraged — set an explicit "
                    "origin allowlist."
                )
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]
    if settings.app_env.lower() in _DEV_ENVS:
        return ["*"]
    # Production default: the app's own origin.
    return [settings.app_base_url.rstrip("/")]


_allow_origins = _resolve_cors_origins()

app.add_middleware(LicenseGuardMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(vehicles.router, prefix="/api")
app.include_router(convoys.router, prefix="/api")
app.include_router(routing.router, prefix="/api")
app.include_router(organizations.router, prefix="/api")
app.include_router(tracking.router, prefix="/api")
app.include_router(weather.router, prefix="/api")
app.include_router(overpass.router, prefix="/api")
app.include_router(status.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(admin_router.router, prefix="/api")
app.include_router(setup_router.router, prefix="/api")
app.include_router(leitstellen.router, prefix="/api")
app.include_router(branding_router.router, prefix="/api")
app.include_router(email_template_router.router, prefix="/api")
app.include_router(license_router.router, prefix="/api")
app.include_router(share_links_router.router, prefix="/api")
app.include_router(track_router.router, prefix="/api")
app.include_router(track_router.ws_router, prefix="/api")
app.include_router(version_router.router, prefix="/api")

_uploads_dir = Path("/uploads")
try:
    _uploads_dir.mkdir(parents=True, exist_ok=True)
except OSError:
    pass  # directory may already exist or be read-only in dev/test environments
if _uploads_dir.is_dir():
    app.mount("/uploads", StaticFiles(directory="/uploads", html=False), name="uploads")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.5.0"}
