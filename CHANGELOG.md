# Changelog

All notable changes to ConvoyPlan are documented here.

---

## [Unreleased]

### Fixed

- **Updater – Selbst-Neustart-Race-Condition behoben.** Der Updater rief intern `docker compose up -d updater` auf, um sich nach jedem Update neu zu erstellen — der orchestrierende Compose-Client wurde dabei beim eigenen Stopp gekillt, sodass der neue Container in `Created` hängen blieb (`<hex>_<project>-updater-1`). Stattdessen startet jetzt ein detachter Helper-Container (`docker:24-cli`) den Recreate, der den Tod des alten Updaters überlebt.
- **Updater – Stack-Datei wird wieder zurückgeschrieben.** `_update_stack_file` nutzte `docker cp $self:/tmp/foo $HOST_PATH`, was im CLIENT-Dateisystem (= im Updater-Container) endete, wo der Host-Pfad nicht existiert; Schreibversuch verlief still im Sand. Schreibt jetzt direkt zum Bind-Mount `/stack/docker-compose.yml`, mit Sidecar-Container als Fallback. Der `:ro`-Flag auf dem Bind-Mount in `docker-compose.yml` wurde entfernt.
- **Updater – pullt sich jetzt selbst.** Bisher wurden alle Service-Images außer dem Updater gepullt — neue Updater-Image-Versionen kamen so nie an. `do_update` pullt jetzt alle Services inkl. Updater; nur das Recreate des Updaters bleibt dem Helper überlassen. Damit verteilen sich zukünftige Updater-Bugfixes automatisch.

### Added

- **Security-Audit-Log.** Append-only Protokoll sicherheitsrelevanter Ereignisse (Login-Erfolg/-Fehlschlag, MFA-Aktivierung/-Deaktivierung, Passwortänderung/-Reset, Benutzer-/Org-Anlage und -Löschung, Lizenzaktivierung) inkl. Akteur, Ziel, IP und User-Agent. Einsehbar für Superadmins unter `GET /api/admin/audit-log` (Filter nach Aktion). Neue Migration `0018`.
- **Brute-Force-Schutz.** In-Process-Rate-Limiting auf `/api/auth/login`, `/api/auth/mfa/verify` und `/api/auth/password-reset` (HTTP 429 mit `Retry-After`). Login/MFA zählen nur Fehlversuche, sodass erfolgreiche Logins nicht bestraft werden.
- **Einheitliche Passwort-Policy + Breach-Check.** Mindestens 10 Zeichen sowie Buchstaben und Ziffern; zusätzlich Abgleich gegen die Have-Ich-Been-Pwned-Range-API (k-Anonymity, fail-open bei fehlender Netzanbindung). Konsistent in Registrierung, Passwortänderung und Admin-Benutzerverwaltung. Abschaltbar über `PASSWORD_BREACH_CHECK_ENABLED=false`.
- **Dependency-Scanning.** `.github/dependabot.yml` (pip/npm/GitHub-Actions/Docker) sowie ein CI-Job `dependency-audit` (`pip-audit` + `npm audit`), zunächst advisory.
- **Detailplan Retention & Betroffenenrechte.** `docs/iso-t5-retention-plan.md` (T5/T5b).
- **Security-Header (Caddy).** `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` und `Permissions-Policy` werden ausgeliefert; `Server`-Header entfernt.
- **`security.txt` & `SECURITY.md`.** Vulnerability-Disclosure-Kontakt unter `/.well-known/security.txt`.
- **ISO-Zertifizierungs-Bewertung.** `docs/iso-certifications-review.md` mit Normen-Priorisierung und code-gestützter Gap-Analyse.
- **Host-Watchdog (systemd-Timer).** `scripts/install.sh` installiert einen `convoyplan-updater-watchdog.timer`, der alle 2 Minuten verwaiste Updater-Container aufräumt und einen fehlenden/abgestürzten Updater neu startet. Defense-in-Depth gegen zukünftige Self-Restart-Probleme. Wird auf Systemen ohne systemd übersprungen.

### Changed

- **Superadmin-Login in `/admin` integriert.** Die separate Route `/login` wurde entfernt; `/admin` ist jetzt self-gated: nicht angemeldete Aufrufe zeigen direkt die Anmeldemaske (inkl. MFA und Passwort-vergessen) und leiten nach erfolgreichem Login ohne Umweg ins Portal durch. Im Superadmin-Portal gibt es jetzt einen **Abmelden**-Button.

### Security

- **Fail-Closed bei unsicherem `JWT_SECRET`.** Im Produktionsmodus (`APP_ENV=production`, Default) verweigert das Backend den Start, wenn `JWT_SECRET` leer, der Platzhalter-Default oder kürzer als 32 Zeichen ist. Für lokale Entwicklung mit `APP_ENV=development` deaktivierbar. Von den Installern generierte Secrets (`openssl rand -hex 32`) erfüllen die Anforderung bereits.
- **CORS-Lockdown in Produktion.** Statt `*` fällt CORS in Produktion auf die eigene App-Origin (`APP_BASE_URL`) zurück; eine explizite Allowlist ist über `CORS_ORIGINS` setzbar. `*` nur in Entwicklung bzw. bei expliziter Konfiguration (mit Warnung).

### Migration

Bestehende Installationen mit alter, kaputter Updater-Version können sich nicht selbst auf die fixe Version aktualisieren (der kaputte Code ist der Code, der das Update macht). Einmalig zur Recovery auf dem Host ausführen:

```bash
curl -fsSL https://convoyplan.de/install.sh | bash
```

Das ruft den Update-Modus auf: räumt verwaiste Updater-Container auf, zieht alle Images (inkl. Updater), recreatet den Stack mit der neuen Compose-Datei und installiert den systemd-Watchdog. Danach läuft alles automatisch.

---

## [0.8.5] – 2026-05-28

### Added

- **Multi-Tenancy / Org-System** – vollständige Mandantenfähigkeit: jede Organisation erhält einen kurzen HiOrg-Code (4–8 Zeichen) als URL-Slug (`/[org-code]/`); Org-Guard-Layout schützt alle org-spezifischen Routen; org-spezifische Login-Seite mit eigenem Branding; `orgStore` mit persistentem Slug und org-bewusstem API-Client.
- **Superadmin: Org anlegen** – Superadmins können direkt im Admin-Panel neue Organisationen erstellen und Benutzer Organisationen zuweisen; Org-Zuordnung im Benutzer-Bearbeiten-Modal.
- **Org-Admin-Panel** – neuer Bereich `/[org-code]/admin/` mit Mitglieder-Tab (Rollen verwalten, Mitglieder einladen) und Export-Tab in der Hauptnavigation.
- **MFA (TOTP)** – Zwei-Faktor-Authentifizierung per TOTP (z. B. Google Authenticator); Einrichtung und Verwaltung im Org-Admin-Panel; SSE-Reconnect mit exponentialem Backoff.
- **SMTP-Service & Passwort per E-Mail** – integrierter SMTP-Dienst; Passwörter können direkt per E-Mail an Benutzer versandt werden; separate Schaltflächen „Passwort generieren" und „E-Mail senden" pro Benutzer im Admin-Panel.
- **GitHub-Token im Superadmin-Panel** – `GITHUB_TOKEN` für authentifizierten Update-Fetch direkt in der Admin-UI konfigurierbar, kein Neustart erforderlich.
- **Live-Update-Log-Terminal** – Echtzeit-Ausgabe des Updater-Prozesses im Browser via SSE; sofortiges Feedback nach Update-Trigger; SSE-Endpoint mit Caddy `flush_interval -1` für verlustfreies Streaming.
- **GIT_SHA im Backend** – der aktuell installierte Commit-SHA wird beim Build eingebettet und in der Updater-Statusanzeige angezeigt.

### Changed

- Plan-Routen und Admin-Routen vollständig unter den Org-Scope verschoben (`/[org-code]/plan/…`, `/[org-code]/admin/`); alte Pfade `/plan` und `/admin` leiten automatisch um.
- Startseite (`/`) ist jetzt öffentlich zugänglich; zeigt einen Org-Code-Hinweis für bestehende Benutzer.
- Setup-Wizard Schritt „Erste Organisation" legt slug-basierte Org beim Erststart an.
- Fahrzeug-Datenbankmodell direkt über `org_id`-Spalte an Org gebunden statt über Benutzer-Join (schnellere Queries, korrekte Isolation).
- Org-Login-Seite und Org-Code-Startseite verwenden das jeweilige Org-Branding.

### Fixed

- **Updater – `STACK_FILE_PATH` nie in `.env` geschrieben** – der Updater konnte den Stack nicht neu starten, weil die Variable fehlte; wird jetzt beim Start via Docker-Labels exportiert und korrekt in die Umgebung übergeben.
- **Updater – Self-Healing** – der Updater erkennt fehlgeschlagene Starts und fährt den Stack kontrolliert neu hoch; Installer unterstützt jetzt auch Update-Mode für bestehende Installs.
- **install.ps1** – falsche Image-Namen und fehlende Updater-Umgebungsvariablen korrigiert; Updater-Image in Release-Workflow und CI-Build-Check aufgenommen.
- **SSE-Streaming hinter Caddy** – `flush_interval -1` am Update-Log-Endpoint gesetzt; Terminal gibt innerhalb von 10 Sekunden nach Trigger erstes Feedback.
- **Org-Isolation bei Fahrzeugen** – Cross-Org-Vehicle-Assignment durch Rollen-Enum-Validierung verhindert; Single-Query-Isolation wiederhergestellt.
- **Superadmin-Panel** – `/admin` nach Multi-Tenancy-Merge wieder erreichbar; Login-Redirect-Logik korrigiert.
- **SSR-Guards** – `orgStore` localStorage-Methoden mit SSR-Guards abgesichert.
- Migration 0013 mit Guards gegen Teilausführung und korrigierter Revision-ID.
- Tabellenlayout im Admin-Panel nach Spaltenänderungen korrigiert.
- Doppelter Tagline auf der Login-Seite entfernt.

---

## [0.5.3] – 2026-05-26

### Fixed

- **Lizenzvalidierung schlug immer fehl** – der Lizenzmanager kodiert das Ablaufdatum als `"exp"` (JWT-Konvention); das Backend las nur `"expires"` → leerer String → Lizenz galt immer als abgelaufen. Beide Feldnamen werden jetzt akzeptiert; Fallback auf Unix-Timestamp (integer) ergänzt.

---

## [0.5.2] – 2026-05-26

### Fixed

- **Leitstellen konnten nicht geladen werden** – `GET /api/leitstellen` (ohne Trailing Slash) löste einen FastAPI-307-Redirect aus; hinter Caddy enthielt der `Location`-Header `http://` statt `https://`, was der Browser als Mixed Content blockierte. Frontend-API-Calls auf `/api/leitstellen/` und `/api/leitstellen/` (POST) korrigiert.

---

## [0.5.1] – 2026-05-24

### Added

- **Demo-Modus** – ohne gültigen Lizenzschlüssel startet die App im Demo-Modus: Lesezugriffe (GET) sind uneingeschränkt möglich, schreibende Operationen (POST/PUT/PATCH/DELETE) werden mit HTTP 402 abgewiesen.
- **Lizenzaktivierung über Admin-UI** – neuer Abschnitt im Admin-Tab „System": zeigt die Instanz-UUID (mit Kopieren-Button) und ein Eingabefeld für den Lizenzschlüssel; nach erfolgreicher Aktivierung wird der Middleware-Cache ohne Serverneustart zurückgesetzt.
- **Lizenzschlüssel-Persistenz in DB** – der eingegebene Schlüssel wird in `system_settings` (`license.key`) gespeichert und überlebt Neustarts; Auflösung in der Reihenfolge: Env-Variable `LICENSE_KEY` → DB-Eintrag.
- **`POST /api/license/activate`** – neuer Superadmin-Endpoint: validiert, speichert und setzt den Middleware-Cache atomar.
- **`GET /api/license/status`** – gibt jetzt zusätzlich `demo_mode` und `key_source` zurück.

### Added (continued)

- **Installer-Scripts** – interaktive One-liner-Installatoren für Linux (`install.sh`) und Windows (`install.ps1`); prüfen Voraussetzungen, fragen Domain/E-Mail/Datenbankpasswort/OSM-Region, generieren `JWT_SECRET` automatisch und starten den Stack.
- **Lizenzmodell (AGPL-3.0 + Dual-Lizenz)** – Demo-Modus und eine Produktivinstallation dauerhaft kostenlos; `COMMERCIAL_LICENSE.md` und `CLA.md` dokumentieren kommerzielle Optionen und Contributor-Bedingungen.
- **CLAUDE.md** – Cross-Repo-Sync-Anweisungen für Installer-Scripts zwischen App- und Website-Repo.

### Fixed

- Backend- und Frontend-Versionsstring auf `0.5.0` korrigiert (war irrtümlich auf `0.4.0` bzw. `0.0.1` geblieben).
- CI-Lizenzschlüssel-Abhängigkeit entkoppelt: `conftest.py` setzt den Middleware-Cache vor Testbeginn, damit Tests nach Keypair-Rotation nicht fehlschlagen.

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
- **`stack.yml`** – production Compose file with all services including Caddy and shared certificate volume.
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

[Unreleased]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.8.5...HEAD
[0.8.5]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.5.3...v0.8.5
[0.5.3]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/RettTechSolutions/ConvoyPlan/releases/tag/v0.1.0
