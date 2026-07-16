import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import jwt as _jwt
from jwt.exceptions import InvalidTokenError

from app.api.routes import (
    auth, convoys, vehicles, routing, organizations,
    tracking, weather, overpass, status, users, leitstellen, traffic, geocoding,
)
from app.api.routes import org_branding as org_branding_router
from app.api.routes import org_leitstellen as org_leitstellen_router
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

Alternativ akzeptieren organisationsbezogene Endpunkte einen **API-Key** per
Header `X-API-Key`. API-Keys werden im Superadmin-Portal je Organisation
erstellt, besitzen eine feste Rolle und sind für den programmatischen Zugriff
durch Fremdsysteme gedacht.

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
    {"name": "traffic", "description": "Live-Verkehrslage (HERE/TomTom) — aktiv bei gesetztem API-Key."},
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
    if not settings.mfa_encryption_key.strip():
        logger.warning(
            "MFA_ENCRYPTION_KEY is not set. MFA secrets are encrypted using a key "
            "derived from JWT_SECRET, which means rotating JWT_SECRET will invalidate "
            "all existing MFA enrolments. Set MFA_ENCRYPTION_KEY to an independent "
            "Fernet key (generate with: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\") to decouple the two secrets."
        )


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _verify_security_config()
    # Update-Benachrichtigung (Modus "notify"): prüft periodisch, ob im
    # aktiven Kanal ein Update verfügbar ist, und mailt die Superadmins.
    # Schläft vor dem ersten Check, belastet den Start also nicht.
    from app.services.update_notify import update_notify_loop
    notify_task = asyncio.create_task(update_notify_loop())
    try:
        yield
    finally:
        # Sauberes Herunterfahren: Task abbrechen und auf sein Ende warten.
        # CancelledError ist dabei der Normalfall; gather liefert ihn (statt
        # ihn zu werfen), sodass der Shutdown nie an ihm scheitert.
        notify_task.cancel()
        outcome = await asyncio.gather(notify_task, return_exceptions=True)
        logger.debug("Update-Notify-Task beendet: %r", outcome)


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
    version=settings.app_version,
    description=_API_DESCRIPTION,
    openapi_tags=_TAGS_METADATA,
    contact={"name": "RettTech Solutions", "url": "https://convoyplan.de"},
    license_info={"name": "Proprietär — RettTech Solutions"},
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=_lifespan,
)


_DOCS_COOKIE_TTL = timedelta(hours=8)


def _issue_docs_cookie() -> str:
    """Mint a short-lived, signed session token for the docs UI. It marks the
    browser as authorised after a successful key check — the API key itself is
    never stored client-side, only this server-signed (JWT_SECRET) claim."""
    expire = datetime.now(timezone.utc) + _DOCS_COOKIE_TTL
    return _jwt.encode(
        {"docs": True, "exp": expire}, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )


def _docs_cookie_valid(token: str) -> bool:
    try:
        payload = _jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except InvalidTokenError:
        return False
    return bool(payload.get("docs"))


def _guard_docs(request: Request) -> bool:
    """Authorise a docs request. Returns True if the key came from the query
    string (so the caller should persist a session cookie). Raises 401 when a
    key is configured but the request did not supply a matching credential."""
    expected = settings.docs_api_key
    if not expected:
        return False  # unprotected (dev convenience)
    # Raw key via query string or header → valid; remember via cookie if it
    # came from the query string so the browser can load the assets afterwards.
    raw = request.query_params.get("key") or request.headers.get("x-api-key")
    if raw and secrets.compare_digest(raw, expected):
        return request.query_params.get("key") == raw
    # Previously authorised browser session: signed, expiring token cookie.
    cookie = request.cookies.get(_DOCS_COOKIE)
    if cookie and _docs_cookie_valid(cookie):
        return False
    raise HTTPException(
        status_code=401,
        detail="Docs-Zugriff erfordert einen gültigen API-Key (z. B. /docs?key=…).",
    )


def _set_docs_cookie(response, request: Request) -> None:
    response.set_cookie(
        _DOCS_COOKIE,
        _issue_docs_cookie(),
        max_age=int(_DOCS_COOKIE_TTL.total_seconds()),
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
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Requested-With"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(vehicles.router, prefix="/api")
app.include_router(convoys.router, prefix="/api")
app.include_router(routing.router, prefix="/api")
app.include_router(organizations.router, prefix="/api")
app.include_router(tracking.router, prefix="/api")
app.include_router(weather.router, prefix="/api")
app.include_router(overpass.router, prefix="/api")
app.include_router(traffic.router, prefix="/api")
app.include_router(geocoding.router, prefix="/api")
app.include_router(status.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(admin_router.router, prefix="/api")
app.include_router(setup_router.router, prefix="/api")
app.include_router(leitstellen.router, prefix="/api")
app.include_router(org_leitstellen_router.router, prefix="/api")
app.include_router(branding_router.router, prefix="/api")
app.include_router(org_branding_router.router, prefix="/api")
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
    return {"status": "ok", "version": settings.app_version}
