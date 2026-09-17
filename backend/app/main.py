import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import docs_ui
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
from app.api.routes import region as region_router
from app.api.routes import setup as setup_router
from app.api.routes import share_links as share_links_router
from app.api.routes import system_metrics as system_metrics_router
from app.api.routes import track as track_router
from app.api.routes import mcp_consent as mcp_consent_router
from app.api.routes import org_mcp as org_mcp_router
from app.api.routes import public_meta as public_meta_router
from app.api.routes import version as version_router
from app.config import settings
from app.middleware.activity import ActivityMiddleware
from app.mcp import mount as mcp_mount
from app.middleware.license_guard import LicenseGuardMiddleware

logger = logging.getLogger(__name__)

_INSECURE_JWT_SECRETS = {"", "changeme-in-production", "change-me-generate-a-real-secret"}
_DEV_ENVS = {"dev", "development", "local", "test", "testing"}
# Tokens are symmetric (HMAC), so the verification key is the signing key. Any
# other family would either not verify against JWT_SECRET at all, or — for
# "none" — accept unsigned tokens, letting anyone mint `is_superadmin: true`.
_ALLOWED_JWT_ALGORITHMS = {"HS256", "HS384", "HS512"}

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

Für Monitoring gibt es zusätzlich **System-API-Keys** (Geltungsbereich *System*):
Sie gehören keiner Organisation und öffnen ausschließlich die lesenden Endpunkte
der Systemübersicht unter `/api/admin/system`. Beide Key-Arten sind strikt
getrennt — ein Org-Key erreicht die Systemkennzahlen nicht, ein System-Key keine
Organisationsdaten.

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
    {
        "name": "system-metrics",
        "description": (
            "Systemübersicht: Live-Zustand von Hardware und Containern, historische "
            "Kennzahlen (bis zu einem Jahr und mehr) sowie Monatsberichte als JSON, CSV "
            "oder PDF. Lesend erreichbar mit Superadmin-Token oder System-API-Key; das "
            "Auslösen einer Stichprobe bleibt Superadmins vorbehalten."
        ),
    },
    {"name": "version", "description": "Versions- und Build-Informationen."},
]


def _verify_security_config() -> None:
    """Fail-closed: refuse to start in production with a weak JWT secret.

    Generate a strong value with `openssl rand -hex 32` and set JWT_SECRET.
    Relax for local work with APP_ENV=development.
    """
    # Checked in every environment, development included: `alg=none` disables
    # signature verification outright, so there is no setup in which it is the
    # right value — an attacker could then self-sign `is_superadmin: true`.
    if settings.jwt_algorithm.upper() not in _ALLOWED_JWT_ALGORITHMS:
        raise RuntimeError(
            f"Unsupported JWT_ALGORITHM {settings.jwt_algorithm!r}: ConvoyPlan signs "
            f"tokens with a shared secret, so only {sorted(_ALLOWED_JWT_ALGORITHMS)} "
            "are accepted. Leave it unset to use the default (HS256)."
        )
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


async def _heal_caddy_config() -> None:
    """Bring an already-installed instance up to the current proxy baseline.

    The setup wizard writes /certs/Caddyfile once and Caddy prefers it over its
    env-var fallback forever after, so an install predating a change would keep
    serving the old routing no matter how often the images are updated.
    Checking (and regenerating) it on boot is what actually delivers such
    changes to those deployments — first the hardening headers, now also the
    MCP/OAuth routes at the site root.
    """
    from app.database import get_db_session
    from app.services.caddy_config import ensure_caddyfile_current

    try:
        async with get_db_session() as db:
            await ensure_caddyfile_current(db)
    except Exception:
        # Never block startup on this — the DB may still be warming up, and an
        # unhardened proxy is strictly better than a backend that will not boot.
        logger.warning("Caddy security-header self-check skipped", exc_info=True)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _verify_security_config()
    await _heal_caddy_config()
    # Update-Benachrichtigung (Modus "notify"): prüft periodisch, ob im
    # aktiven Kanal ein Update verfügbar ist, und mailt die Superadmins.
    # Schläft vor dem ersten Check, belastet den Start also nicht.
    from app.services.update_notify import update_notify_loop
    from app.services.deploy_alert import deploy_alert_loop
    from app.jobs.metrics import metrics_collector_loop
    notify_task = asyncio.create_task(update_notify_loop())
    # Watches /update_status/deploy_alert.json for failed-deploy / auto-rollback
    # / aborted-boot markers written by the updater and entrypoint, and emails
    # the superadmins about them (once per event).
    alert_task = asyncio.create_task(deploy_alert_loop())
    # Erfasst periodisch Hardware-, Container- und Nutzungskennzahlen für die
    # Systemübersicht im Admin-Portal. Läuft hier (und nicht im retention-
    # Container), weil die Nutzungsdaten im Speicher dieses Prozesses liegen.
    metrics_task = asyncio.create_task(metrics_collector_loop())
    try:
        # Der Streamable-HTTP-Transport des MCP-Servers braucht eine laufende
        # Task-Group. Ohne das scheitert der erste MCP-Request mit einem
        # RuntimeError — bei abgeschaltetem MCP ist das ein No-op.
        async with mcp_mount.lifespan_context():
            yield
    finally:
        # Sauberes Herunterfahren: Tasks abbrechen und auf ihr Ende warten.
        # CancelledError ist dabei der Normalfall; gather liefert ihn (statt
        # ihn zu werfen), sodass der Shutdown nie an ihm scheitert.
        notify_task.cancel()
        alert_task.cancel()
        metrics_task.cancel()
        outcome = await asyncio.gather(
            notify_task, alert_task, metrics_task, return_exceptions=True
        )
        logger.debug("Hintergrund-Tasks beendet: %r", outcome)


# Interactive docs are always on in development. In production they are off by
# default so the API surface is not exposed publicly; enable them either openly
# via ENABLE_DOCS=true or — preferred for externally reachable hosts —
# protected by setting DOCS_API_KEY (which implies the docs are served).
# Gate, Anmeldeformular und Cookie liegen in app/api/docs_ui.py.
_docs_enabled = docs_ui.docs_enabled()

# We render the docs ourselves (docs_ui.register below) so they can be gated
# behind DOCS_API_KEY, so the built-in routes are always disabled here.
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

if _docs_enabled:
    docs_ui.register(app)


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
# Zählt Requests und aktive Benutzer für die Systemübersicht. Bewusst *innerhalb*
# von CORS eingehängt: OPTIONS-Preflights beantwortet die CORS-Middleware selbst
# und sollen nicht als Portalnutzung erscheinen.
app.add_middleware(ActivityMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_origins != ["*"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization", "Content-Type", "X-API-Key", "X-Requested-With",
        # Streamable HTTP: der Client führt die Sitzung über diesen Header,
        # und ab Protokollversion 2025-06-18 schickt er zusätzlich die
        # ausgehandelte Version mit.
        "Mcp-Session-Id", "MCP-Protocol-Version", "Last-Event-ID",
    ],
    # Ohne expose_headers kommt der Browser nicht an die Session-Id heran —
    # rein serverseitige Clients merken das nicht, der MCP Inspector schon.
    expose_headers=["Mcp-Session-Id"],
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
app.include_router(region_router.router, prefix="/api")
app.include_router(region_router.admin_router, prefix="/api")
# Oeffentlich (kein require_superadmin): der Regionsumriss fuer die
# Kartenmaske. Wird auch von den Tracking- und Freigabekarten gebraucht, die
# ohne Anmeldung laufen — siehe Kommentar an `region_router.public_router`.
app.include_router(region_router.public_router, prefix="/api")
app.include_router(system_metrics_router.router, prefix="/api")
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
app.include_router(mcp_consent_router.router, prefix="/api")
app.include_router(org_mcp_router.router, prefix="/api")
# Selbstauskunft für Maschinen: die öffentliche OpenAPI-Teilmenge unter
# /api/public/openapi.json und die Protected Resource Metadata der REST-API
# an der Wurzel. Beide bewusst ohne Anmeldung — sie sind der Einstieg, den
# ein Agent braucht, bevor er überhaupt Zugangsdaten hat.
app.include_router(public_meta_router.router, prefix="/api")
app.include_router(public_meta_router.wellknown_router)

# MCP-Server. Hängt /mcp sowie die OAuth- und Well-Known-Routen an die
# Wurzel — und tut nichts, solange MCP_ENABLED nicht gesetzt ist.
mcp_mount.mount(app)

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
