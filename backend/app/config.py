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

    # Release channel for the self-updater. "stable" only deploys published
    # GitHub *releases* (so a normal push to main no longer triggers an update);
    # "beta" tracks every commit on the main branch (the previous behaviour).
    # The admin-panel toggle (system_settings: "update.channel") takes priority;
    # this env value is only the fallback when no DB setting exists.
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
    rate_limit_enabled: bool = True

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
    # CA-/Vertrauenskette (PEM) zum Verifizieren des Broker-Servers, wenn dieser
    # eine private CA nutzt (mobilithek-M2M-Broker: prod-mdp.m2m.de). Pfad zur
    # PEM-Datei mit der M2M-CA-Kette. Leer = öffentlicher Trust-Store.
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

    # Optional API key that protects the interactive docs. When set, the docs
    # are served (no ENABLE_DOCS needed) but require the key: open
    # /docs?key=<value> once (the key is remembered in an HttpOnly cookie), or
    # send it as the X-API-Key header. Recommended when the host is reachable
    # externally. Leave empty to serve the docs unprotected (dev convenience).
    docs_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
