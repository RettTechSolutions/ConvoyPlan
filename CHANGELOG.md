# Changelog

All notable changes to MarschPlan are documented here.

---

## [Unreleased]

---

## [0.5.0] – 2026-05-18

### Added

- **Organisations-Rollenmodell** – feingranulare Zugriffskontrolle auf Konvoi- und Fahrzeugendpoints (`get_convoy_access`, `get_vehicle_access`). Lesen ab Beobachter-Rolle, Schreiben ab Fahrer- bzw. Planer-Rolle; WebSocket-Handler prüft Konvoi-Zugehörigkeit und Fahrer-Rolle für Positionsschreibzugriff.
- **GPX/GeoJSON-Import** – Parser-Service für GPX-Tracks und GeoJSON-FeatureCollections; REST-Endpunkte `POST /api/convoys/{id}/import/gpx` und `.../geojson`; Import-UI im Export-Tab der Planungsseite mit Datei-Upload und Reset.
- **Leitstellen** – vollständiges CRUD-Datenmodell (`Leitstelle`, GeoJSON/KML-Grenzimport); Admin-Tab mit Polygon-Zeichnung direkt auf der Karte; automatische Berechnung von Kanalwechseln beim Routingdurchlauf; Anzeige im Zeitplan-Tab, Marschbefehl-Modal und PDF-Export.
- **Branding-System** – CSS Custom Properties für alle Markenfarben; Branding-API (`GET/PUT /api/admin/branding`) mit Logo-Upload und persistentem `BrandingConfig`-JSON; Branding-Tab im Admin-Panel mit Live-Vorschau; Branding-Schritt (Schritt 3) im Setup-Wizard.
- **Design-Token-System und Dark/Light-Theme** – vollständiges Token-Set (Farben, Typografie, Abstände, Radien, Schatten) mit CSS-Variablen; `ThemeStore` mit `localStorage`-Persistenz und SSR-Guard; Theme-Toggle in der Seitenleiste; Token-Migration für Plan-, Admin-, Tracking-, Login- und Share-Seiten.
- **Auto-Updater** – separater Docker-Container `updater` mit Git-Poll-Schleife (5-Minuten-Intervall); authentifizierter Fetch via `GITHUB_TOKEN`; `git reset --hard` für saubere Deploys; schreibt `status.json` auf gemeinsames Volume; reagiert auf manuelles Trigger-Flag.
- **Update-Status-Admin-UI** – neuer Tab "System" im Admin-Panel zeigt letzten Check-Zeitstempel, aktuellen und verfügbaren Commit-SHA sowie Update-Status; Schaltfläche zum manuellen Auslösen eines Updates via `POST /api/admin/trigger-update`.
- **Konvoi-Einstellungen bearbeiten** – bestehende Konvois können nach der Erstellung vollständig editiert werden (Name, Beschreibung, Start-/Endzeit, Geschwindigkeitsprofile).

### Changed

- Fahrzeugliste zeigt alle Org-Mitglieder (nicht nur Owner); Lese- und Schreibzugriff durch Rollen-Guards gesteuert.
- Seitenleiste der Planungsseite komplett auf Design-Tokens umgestellt; theme-bewusste Hintergrundfarbe.
- Tracking-Ansicht auto-zoomt beim Laden auf die berechnete Route.
- `docker-compose.yml`: `updater`-Service mit `update_status`-Volume; `GITHUB_TOKEN` wird an Backend weitergegeben.
- Backend-Version auf `0.5.0` erhöht.

### Fixed

- Backend-Bind-Mount entfernt; Code läuft im Produktionsbetrieb ausschließlich aus dem gebauten Image.
- `toggleTheme` mit SSR-Guard für `localStorage`-Zugriff abgesichert.
- Kanalwechsel-Geometrie-Binding und MultiPolygon-Handling korrigiert.
- Branding-Response-Typ korrekt gecastet.
- `mapMode` in MapView-Click-Handler via `get()` für Svelte-5-Kompatibilität gelesen.
- CSS-Variablen beim Tab-Wechsel wiederhergestellt; Branding-Formular nach Speichern synchronisiert.
- Expliziten Compose-Projektnamen gesetzt, um Workspace/marschplan-Namenskonflikt zu vermeiden.
- `git safe.directory` für gemounteten Workspace im Updater-Container gesetzt.
- Updater-Skript gegen Self-Kill bei laufendem Compose-Neustart abgesichert.

---

## [0.4.0] – 2026-05-07

### Added

- **First-run Setup Wizard** – browser-based wizard at `/setup` creates the superadmin account, configures the server domain and SSL mode (Let's Encrypt, custom certificate, or internal self-signed) in three steps. Setup is only accessible before any superadmin exists; the app redirects automatically on first start.
- **Caddy reverse proxy** – Caddy 2 replaces plain HTTP serving. Handles TLS termination, automatic Let's Encrypt certificates, and WebSocket proxying. Admin API at `:2019` enables live config reload without container restarts.
- **SSL certificate upload** – custom PEM certificates can be uploaded directly in the setup wizard via file picker; stored on a named Docker volume shared with Caddy.
- **Live Caddy reload** – `POST /api/setup` writes the Caddyfile and reloads Caddy via its admin API immediately, no container restart required. Config persists across restarts via the shared volume.
- **Admin API** – `GET/PATCH /api/admin/users` for superadmin user management including activation, deactivation, and role changes.
- **Self-demotion guard** – superadmins cannot remove their own superadmin status or deactivate themselves.
- **Setup atomicity** – PostgreSQL advisory lock prevents concurrent setup requests from creating duplicate superadmins.
- **Three-tier RBAC** – superadmin / org-admin / user roles with consistent `_get_org_admin` helper used across all organisation endpoints.
- **`system_settings` table** – migration `0008_settings` stores domain, TLS mode, and ACME email from the setup wizard.
- **`portainer-stack.yml`** – ready-to-use Portainer stack with all services including Caddy and shared certificate volume.
- **`.env.example`** – complete reference for all production environment variables.

### Changed

- Superadmin account is now created via the setup wizard instead of environment variables (`SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` removed).
- WebSocket URL in tracking store uses `window.location.host` instead of hardcoded `:8000`, routing correctly through Caddy in production.
- `docker-compose.yml`: `cert_uploads` named volume replaces `${CERT_DIR}` bind-mount for Caddy; `caddy` service added with environment-variable-based Caddyfile generation as fallback on first start.
- Layout redirect sequences setup-status check before auth redirect, eliminating flash of `/login` on fresh installs.
- Backend version bumped to `0.4.0`.

### Fixed

- Organisation invite form initialisation: `orgInviteForm` initialised in `toggleOrgExpand` instead of inline assignment-as-expression in `bind:value`.
- Invite error cleared on successful invite submission.
- `organizations.py` `invite_member` now uses `_get_org_admin` for consistent owner-level check.
- `key.pem` written with `chmod 0o600` for correct file permissions.
- Caddy `adapt` response correctly unwraps `{"result": ..., "warnings": [...]}` envelope before posting to `/load`.
- `SystemSetting.value` uses `server_default=""` (not `default=""`) for correct DB-level default.

---

## [0.3.0] – 2026-05-06

### Added

- **Dashboard overlays** – weather widget, Overpass road-closure overlay, and status bar shown directly on the planning map.
- **Responsive layout** – mobile-first sidebar and map layout with collapsible panels.
- **Routing improvements** – via-point reordering via drag-and-drop, route recalculation on waypoint changes.
- **Waypoint management** – full CRUD for waypoints including stop type, dwell time, and notes; reorderable list.

### Changed

- Convoy planning page reorganised into a tabbed sidebar layout.

---

## [0.2.0] – 2026-05-05

### Added

- **Convoy wizard** – step-by-step wizard for creating a new convoy: name, vehicles, start/end points, waypoints, speed settings.
- **Rebrand to MarschPlan / ConvoyPlan** – updated branding, logo, and colour scheme across frontend and documentation.
- **Sub-convoy support** – convoys can have a parent convoy for multi-echelon march planning.
- **Share tokens** – read-only public link for convoy routes without login.

---

## [0.1.0] – initial

### Added

- FastAPI backend with SQLAlchemy async + Alembic migrations (PostgreSQL 15 + PostGIS).
- SvelteKit frontend with Svelte 5 runes (`$state`, `$effect`, `$derived`).
- JWT authentication (register, login, token refresh).
- Vehicle CRUD with callsign, plate, dimensions, weight, fuel type.
- Convoy CRUD with vehicle assignment.
- GraphHopper routing engine (self-hosted, OSM-based).
- Waypoint types: start, stop, checkpoint, fuel stop.
- Automatic schedule calculation (departure/arrival times, speed-dependent).
- Route export: GPX, JSON, PDF (march order).
- Live tracking via WebSocket + browser Geolocation API.
- Vehicle status: planned, en route, arrived, delayed.
- GeoJSON Lage layers (upload, display, manage).
- Weather integration (Open-Meteo, no API key required).
- Overpass API integration for road closures and construction.
- Organisation / tenancy model with role-based membership.
- PWA manifest + Workbox service worker for offline tile caching.
- Capacitor configuration for Android/iOS native wrapper.
- Docker Compose setup with GraphHopper OSM pre-download.

[Unreleased]: https://github.com/RettTechSolutions/MarschPlan/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/RettTechSolutions/MarschPlan/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/RettTechSolutions/MarschPlan/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/RettTechSolutions/MarschPlan/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/RettTechSolutions/MarschPlan/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/RettTechSolutions/MarschPlan/releases/tag/v0.1.0
