from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://convoyplan:convoyplan@localhost:5432/convoyplan"
    jwt_secret: str = "changeme-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days
    graphhopper_url: str = "http://localhost:8989"
    caddy_admin_url: str = "http://caddy:2019"
    github_token: str = ""
    github_repo: str = "RettTechSolutions/ConvoyPlan"

    # Human-readable build version, injected at image build time from the git
    # tag (ARG/ENV APP_VERSION). The scheme is YYYY.MASTER.FIX, e.g. "2026.1.1"
    # (or "2026.1.1-3-g37b9dad" for builds ahead of the last tag). Falls back to
    # a dev placeholder for local runs.
    app_version: str = "0.0.0-dev"

    # Periodically check the GitHub releases API for a newer version so the UI
    # can show an "update available" hint. Fails open (no hint) when GitHub is
    # unreachable, so it is safe in offline/air-gapped deployments. Disabled in
    # tests so the version endpoint never hits the network.
    update_check_enabled: bool = True

    # Release channel for the self-updater:
    #   "stable"  — only deploys published GitHub *releases* (a normal push to
    #               main no longer triggers an update).
    #   "beta"    — tracks numbered GitHub *pre-releases* (release candidates,
    #               e.g. v2026.2.1-beta.1) via the floating :beta images.
    #   "nightly" — tracks every commit on main via the :nightly images (this is
    #               what "beta" meant before the 3-channel split).
    # The admin-panel toggle (system_settings: "update.channel") takes priority;
    # this env value is only the fallback when no DB setting exists. NOTE: the
    # DB migration that renames the old "beta" (every-commit) channel to
    # "nightly" only touches the DB row — installs that select the channel purely
    # via this env var must set UPDATE_CHANNEL=nightly to keep every-commit
    # behaviour (UPDATE_CHANNEL=beta now means pre-releases only).
    update_channel: str = "stable"

    # Update mode for the self-updater. "auto" installs channel updates
    # automatically; "notify" disables automatic installs and emails the
    # superadmins instead (they update manually via the admin panel).
    # The admin-panel toggle (system_settings: "update.mode") takes priority;
    # this env value is only the fallback when no DB setting exists.
    update_mode: str = "auto"
    # How often the backend checks whether an update notification is due
    # (seconds). Relevant for mode "notify" and for notify_on_auto.
    update_notify_interval: int = 1800
    # Optional: also email the superadmins AFTER an update was installed
    # automatically (mode "auto"). The admin-panel checkbox
    # (system_settings: "update.notify_on_auto") takes priority; this env
    # value is only the fallback when no DB setting exists.
    update_notify_on_auto: bool = False

    license_key: str = ""
    app_base_url: str = "https://convoyplan.example.com"

    # Deployment environment. In "production" the app refuses to start with an
    # insecure JWT secret (fail-closed). Set APP_ENV=development to relax this
    # for local work; tests bypass the check (lifespan is not triggered there).
    app_env: str = "production"

    # Brute-force protection for authentication endpoints. Disabled in tests.
    # Also gates the upstream-quota throttles below.
    rate_limit_enabled: bool = True

    # Hourly per-caller budgets for the endpoints that spend a metered upstream
    # quota (see app/api/quota.py). Demo sessions get the smaller budget because
    # anyone can mint one via POST /api/auth/demo-session — without this, a
    # single free session could drain the instance's HERE/TomTom credits or pin
    # GraphHopper's CPU. Set a value to 0 to disable that throttle.
    quota_routing_per_hour: int = 240        # GraphHopper route calculations
    quota_routing_demo_per_hour: int = 40
    quota_geocode_per_hour: int = 600        # HERE / Photon address search
    quota_geocode_demo_per_hour: int = 100
    quota_traffic_per_hour: int = 600        # HERE / TomTom live traffic flow
    quota_traffic_demo_per_hour: int = 100

    # Check new passwords against the Have I Been Pwned k-anonymity range API.
    # Fails open (allows the password) if the service is unreachable, so it is
    # safe in offline/air-gapped deployments. Disabled in tests.
    password_breach_check_enabled: bool = True

    # Comma-separated list of allowed CORS origins, or "*". When unset in
    # production the app falls back to its own origin (see main.py); "*" in
    # development only.
    cors_origins: str = ""

    # Fernet key (urlsafe-base64, 32 bytes) used to encrypt MFA secrets at rest.
    # When empty, a key is derived deterministically from jwt_secret.
    mfa_encryption_key: str = ""

    # Ephemeral demo sessions. The superadmin toggle in the admin panel (stored
    # in system_settings under "demo.enabled") takes priority; DEMO_ENABLED is
    # the fallback when no DB setting exists.
    demo_enabled: bool = False
    # Lifetime of new demo sessions. Like demo_enabled, the admin-panel setting
    # (system_settings: "demo.session_hours") takes priority over this fallback.
    demo_session_hours: int = 24

    # Data retention (DSGVO Art. 5(1)(e)). Run by the `retention` cron container.
    retention_enabled: bool = True
    retention_positions_hours: int = 24      # live positions older than this are purged
    retention_audit_days: int = 365          # audit-log entries older than this are purged
    retention_share_links_days: int = 30     # revoked share links older than this are purged
    # Interactive API docs (Swagger UI at /docs, ReDoc at /redoc, schema at
    # /openapi.json). Always available in development environments. In
    # production they are disabled by default so the API surface is not exposed
    # publicly; set ENABLE_DOCS=true to opt back in (e.g. behind reverse-proxy
    # auth or on an internal network).
    enable_docs: bool = False

    # Offene, lizenzfreie Verkehrsdaten-Feeds (Baustellen/Sperrungen). Jeder
    # Eintrag ist "format|url" (oder nur "url" → Standardformat "mobidata_bw");
    # mehrere Einträge kommasepariert. Unterstützte Formate:
    #   - "mobidata_bw"  MobiData-BW-/CIFS-GeoJSON (Baden-Württemberg)
    #   - "berlin_viz"   Berliner Verkehrsinformationszentrale (GeoJSON)
    #   - "datex2"       DATEX II v2 (europäischer Standard) — z. B. Länder-Feeds
    #                    aus der mobilithek für bundesweite Abdeckung.
    # Weitere Regionen lassen sich hier ergänzen. Leeren String → deaktiviert.
    opendata_traffic_enabled: bool = True
    opendata_traffic_feeds: str = (
        "mobidata_bw|https://api.mobidata-bw.de/datasets/traffic/roadworks/roadworks_geojson.json,"
        "berlin_viz|https://api.viz.berlin.de/daten/baustellen_sperrungen_viz.json"
    )
    # Client-Zertifikat (PEM mit Zertifikat + privatem Schlüssel) für DATEX-II-
    # Feeds, die per mTLS geschützt sind — insbesondere der mobilithek-Broker.
    # Pfad zur PEM-Datei; nur nötig für zugangsbeschränkte "datex2"-Feeds.
    opendata_traffic_client_cert: str = ""
    # CA-/Vertrauenskette (PEM) zum Verifizieren des Broker-Servers — NUR nötig,
    # wenn der Broker eine wirklich private CA nutzt. Leer = öffentlicher
    # Trust-Store (Standard). Achtung: Der mobilithek-Broker (mobilithek.info:8443)
    # nutzt ein öffentliches Telekom-Serverzertifikat — hier NICHT setzen, sonst
    # scheitert die TLS-Verifikation ("self-signed cert in chain").
    opendata_traffic_ca_cert: str = ""

    # Live-Verkehrslage (Fließgeschwindigkeit/Stau) von kommerziellen Anbietern.
    # Vollständig vorbereitet, aber inaktiv, solange kein Key gesetzt ist —
    # sobald eine Installation einen eigenen API-Key hinterlegt, fließt die
    # Verkehrslage automatisch in die Karte. Kein Key ⇒ Feature einfach aus.
    # Hinweis: Die Anzeige von HERE-/TomTom-Verkehrsdaten auf einer
    # OSM-Basiskarte kann lizenzpflichtig sein — vor produktivem Einsatz die
    # Nutzungsbedingungen des jeweiligen Anbieters prüfen (Verantwortung der
    # jeweiligen Installation).
    here_traffic_api_key: str = ""
    tomtom_traffic_api_key: str = ""
    # Bei mehreren gesetzten Keys die Quelle erzwingen ("here"/"tomtom");
    # leer = automatisch (HERE bevorzugt).
    traffic_flow_provider: str = ""

    # HERE-API-Key für die Adresssuche (Geocoding & Search). Ist er gesetzt,
    # läuft die Adresssuche über HERE (serverseitig proxied, der Key verlässt
    # den Server nie); sonst fällt sie auf das offene Photon (komoot) zurück.
    # HERE gibt EINEN Key für alle Produkte aus — ist hier keiner gesetzt, wird
    # automatisch der HERE-Traffic-Key (ENV oder Admin-Panel) mitbenutzt, sodass
    # der Key nur einmal hinterlegt werden muss.
    here_api_key: str = ""

    # Kostendeckel für die HERE-Adresssuche: maximal so viele HERE-Anfragen pro
    # Kalendermonat. Ist der Deckel erreicht, fällt die Adresssuche für den Rest
    # des Monats automatisch auf das kostenlose Photon zurück (kein Ausfall,
    # keine Kosten). Zählt nur echte HERE-Aufrufe; Photon-Anfragen sind gratis
    # und zählen nicht. HEREs Base-Plan enthält 30.000 Transaktionen/Monat
    # gratis — der Standard 25.000 lässt bewusst Puffer, damit nie abgerechnet
    # wird. 0 = kein App-Deckel (dann greift nur HEREs eigenes Kontingent).
    here_monthly_limit: int = 25000

    # Optional API key that protects the interactive docs. When set, the docs
    # are served (no ENABLE_DOCS needed) but require the key: open
    # /docs?key=<value> once (the key is remembered in an HttpOnly cookie), or
    # send it as the X-API-Key header. Recommended when the host is reachable
    # externally. Leave empty to serve the docs unprotected (dev convenience).
    docs_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
