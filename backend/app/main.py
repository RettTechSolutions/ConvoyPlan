import logging
import os
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
from app.api.routes import version as version_router
from app.middleware.license_guard import LicenseGuardMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    yield


app = FastAPI(title="ConvoyPlan API", version="0.5.0", lifespan=_lifespan)

_origins_env = os.environ.get("CORS_ORIGINS", "*")
_allow_origins = [o.strip() for o in _origins_env.split(",")] if _origins_env != "*" else ["*"]

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
