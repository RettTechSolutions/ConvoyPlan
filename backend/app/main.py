import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
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

_API_DESCRIPTION = """
REST-API für **ConvoyPlan** — Planung, Routing und Live-Tracking von Marschkolonnen.

Die meisten Endpunkte sind organisationsbezogen und erfordern einen
**Bearer-Token** (JWT), den du über `POST /api/auth/login` erhältst. Klicke in
Swagger UI oben rechts auf **Authorize** und füge den Token ein, um die
geschützten Endpunkte direkt auszuprobieren.

Ohne gültigen Lizenzschlüssel läuft die API im **Demo-Modus**: lesende Zugriffe
(GET) sind erlaubt, schreibende Zugriffe (POST/PUT/PATCH/DELETE) auf geschützte
Endpunkte antworten mit HTTP `402`.
""".strip()

# Tag-Metadaten: liefert Swagger/ReDoc saubere, gruppierte Abschnitte mit
# Beschreibungen. Die Reihenfolge hier bestimmt die Reihenfolge in der UI.
_TAGS_METADATA = [
    {"name": "auth", "description": "Login, MFA (TOTP), Passwortverwaltung und Token-Ausgabe."},
    {"name": "setup", "description": "Erstmalige Einrichtung der Instanz (Admin-Konto, Basisdaten)."},
    {"name": "license", "description": "Lizenzschlüssel hinterlegen, prüfen und Demo-Status abfragen."},
    {"name": "organizations", "description": "Organisationen (Mandanten) verwalten und Mitgliedschaften pflegen."},
    {"name": "users", "description": "Benutzerkonten innerhalb einer Organisation verwalten."},
    {"name": "convoys", "description": "Marschkolonnen anlegen, bearbeiten, Fahrzeuge und Wegpunkte zuordnen."},
    {"name": "vehicles", "description": "Fahrzeugstammdaten der Organisation verwalten."},
    {"name": "routing", "description": "Routen berechnen und optimieren (GraphHopper-Anbindung)."},
    {"name": "tracking", "description": "GPS-Positionen erfassen und abrufen."},
    {"name": "track", "description": "Live-Tracking inkl. WebSocket-Stream für Echtzeit-Updates."},
    {"name": "share-links", "description": "Öffentliche Freigabe-Links für Kolonnen erstellen und verwalten."},
    {"name": "leitstellen", "description": "Leitstellen/Dispositionszentren verwalten."},
    {"name": "weather", "description": "Wetterdaten entlang der Route abrufen."},
    {"name": "overpass", "description": "OpenStreetMap-/Overpass-Abfragen für Kartendaten."},
    {"name": "branding", "description": "Organisationsspezifisches Branding (Logo, Farben) anpassen."},
    {"name": "email-template", "description": "E-Mail-Vorlagen verwalten (Admin)."},
    {"name": "admin", "description": "Administrative Endpunkte für Superadmins."},
    {"name": "status", "description": "System- und Gesundheitsstatus der Instanz."},
    {"name": "version", "description": "Versions- und Build-Informationen."},
]


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


# Interactive docs are always on in development. In production they are off by
# default so the API surface is not exposed publicly; enable them either openly
# via ENABLE_DOCS=true or — preferred for externally reachable hosts —
# protected by setting DOCS_API_KEY (which implies the docs are served).
_DOCS_COOKIE = "convoyplan_docs_key"
_OPENAPI_URL = "/openapi.json"
_docs_enabled = (
    settings.enable_docs
    or bool(settings.docs_api_key)
    or settings.app_env.lower() in _DEV_ENVS
)

# We render the docs ourselves (see _docs/_redoc/_openapi below) so they can be
# gated behind DOCS_API_KEY, so the built-in routes are always disabled here.
app = FastAPI(
    title="ConvoyPlan API",
    version="0.5.0",
    description=_API_DESCRIPTION,
    openapi_tags=_TAGS_METADATA,
    contact={"name": "RettTech Solutions", "url": "https://convoyplan.de"},
    license_info={"name": "Proprietär — RettTech Solutions"},
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=_lifespan,
)


def _docs_key_from_request(request: Request) -> str | None:
    """Pull a supplied docs key from query string, cookie or header (in order)."""
    return (
        request.query_params.get("key")
        or request.cookies.get(_DOCS_COOKIE)
        or request.headers.get("x-api-key")
    )


def _guard_docs(request: Request) -> bool:
    """Authorise a docs request. Returns True if the key came from the query
    string (so the caller should persist it in a cookie). Raises 401 when a key
    is configured but the request did not supply a matching one."""
    expected = settings.docs_api_key
    if not expected:
        return False  # unprotected (dev convenience)
    supplied = _docs_key_from_request(request)
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail="Docs-Zugriff erfordert einen gültigen API-Key (z. B. /docs?key=…).",
        )
    return request.query_params.get("key") == supplied


def _set_docs_cookie(response, request: Request) -> None:
    response.set_cookie(
        _DOCS_COOKIE,
        settings.docs_api_key,
        max_age=8 * 3600,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )


if _docs_enabled:

    @app.get("/openapi.json", include_in_schema=False)
    async def _openapi(request: Request):
        from_query = _guard_docs(request)
        resp = JSONResponse(app.openapi())
        if from_query:
            _set_docs_cookie(resp, request)
        return resp

    @app.get("/docs", include_in_schema=False)
    async def _docs(request: Request) -> HTMLResponse:
        from_query = _guard_docs(request)
        resp = get_swagger_ui_html(openapi_url=_OPENAPI_URL, title="ConvoyPlan API — Swagger UI")
        if from_query:
            _set_docs_cookie(resp, request)
        return resp

    @app.get("/redoc", include_in_schema=False)
    async def _redoc(request: Request) -> HTMLResponse:
        from_query = _guard_docs(request)
        resp = get_redoc_html(openapi_url=_OPENAPI_URL, title="ConvoyPlan API — ReDoc")
        if from_query:
            _set_docs_cookie(resp, request)
        return resp

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
