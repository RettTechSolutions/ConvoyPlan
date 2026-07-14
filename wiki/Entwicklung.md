# Entwicklung

Diese Seite beschreibt die Projektstruktur und den lokalen Entwicklungs-Workflow. Die vollständige Einrichtung (Docker-Quickstart, Konfiguration, Deployment) ist unter [Installation und Setup](Installation-und-Setup) dokumentiert.

---

## Projektstruktur

```text
ConvoyPlan/
├── backend/
│   ├── app/
│   │   ├── api/routes/       # REST- und WebSocket-Endpunkte
│   │   │   ├── auth.py       # Registrierung, Login, MFA, Passwort-Reset
│   │   │   ├── setup.py      # Ersteinrichtungs-Wizard (Status + Ausführen)
│   │   │   ├── admin.py      # Superadmin: Benutzer, Orgs, API-Keys, Audit-Log, DSGVO
│   │   │   ├── leitstellen.py  # Globale Leitstellen und Kanalwechsel
│   │   │   ├── org_leitstellen.py  # Org-eigene Leitstellen + Vorschlags-Workflow
│   │   │   ├── branding.py   # Branding-Konfiguration und Logo-Upload
│   │   │   ├── email_template.py  # E-Mail-Vorlagen (SMTP-Versand)
│   │   │   ├── license.py    # Lizenzstatus, Aktivierung, Instanz-UUID
│   │   │   ├── convoys.py    # Marschverbände, Waypoints, Export
│   │   │   ├── share_links.py  # Widerrufbare Freigabelinks pro Konvoi
│   │   │   ├── track.py      # Eigenständige Tracking-App (REST + WebSocket)
│   │   │   ├── vehicles.py   # Fahrzeugverwaltung
│   │   │   ├── organizations.py  # Organisationen und Mitglieder
│   │   │   ├── tracking.py   # Live-Positionen + WebSocket
│   │   │   ├── routing.py    # GraphHopper-Routing
│   │   │   ├── weather.py    # Open-Meteo-Integration
│   │   │   ├── overpass.py   # Sperrungsabfragen (Overpass, Autobahn-API, offene Feeds, DATEX-II), Punkt und Routenkorridor
│   │   │   ├── traffic.py    # Live-Verkehrslage (HERE/TomTom), Punkt und Routenkorridor
│   │   │   ├── users.py      # Eigenes Benutzerprofil
│   │   │   ├── version.py    # Versions- und Build-Informationen
│   │   │   └── status.py     # Systemstatus
│   │   ├── models/           # SQLAlchemy-Modelle
│   │   ├── schemas/          # Pydantic-Schemas
│   │   ├── services/         # Routing, Zeitplan, Export, Wetter, Overpass/Autobahn/Traffic, Tracking, Retention
│   │   ├── jobs/             # Hintergrundjobs (z. B. Retention-Purge)
│   │   ├── config.py         # Backend-Konfiguration über Umgebungsvariablen
│   │   ├── database.py       # Async-Datenbankanbindung
│   │   └── main.py           # FastAPI-App und Router-Registrierung
│   ├── alembic/              # Datenbankmigrationen (0001–0026)
│   ├── tests/                # pytest-Tests
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/lib/api/          # API-Client
│   ├── src/lib/components/   # Karte, Wetter, Leitstellen-Tabelle/-Karte, UI-Bausteine
│   ├── src/lib/stores/       # Auth-, Karten-, Konvoi-, Tracking-, Org-, Branding-Stores
│   ├── src/routes/
│   │   ├── setup/            # Ersteinrichtungs-Wizard (5 Schritte inkl. Org-Anlage)
│   │   ├── admin/            # Superadmin (self-gated): Benutzer, Orgs, API-Keys, Leitstellen, Branding, System
│   │   ├── o/[slug]/         # Org-Scope (alle org-spezifischen Routen)
│   │   │   ├── login/        # Org-spezifische Anmeldung mit eigenem Branding
│   │   │   ├── plan/         # Planungsansicht mit Karte
│   │   │   ├── tracking/     # Live-Tracking-Ansicht (Übersicht + je Konvoi)
│   │   │   └── admin/        # Org-Admin: Mitglieder, Leitstellen, Branding, System
│   │   ├── track/[slug]/     # Eigenständige Fahrer-Tracking-PWA („Convoy Tracking")
│   │   └── share/[token]/    # Öffentliche Routenansicht ohne Login
│   ├── static/geo/           # Offline-Landkreisgrenzen (GeoJSON) für Leitstellengebiete
│   ├── capacitor.config.ts
│   ├── package.json
│   └── vite.config.ts
├── docker/updater/           # Git-Polling-Container (update.sh, Dockerfile)
├── caddy/
│   └── entrypoint.sh         # Caddyfile-Generierung aus Env-Variablen
├── graphhopper/
│   ├── Dockerfile
│   ├── entrypoint.sh         # OSM-Download und GraphHopper-Start
│   └── config.yml
├── .github/
│   ├── workflows/
│   │   ├── ci.yml            # Tests + Typecheck + Docker-Build + Dependency-Audit
│   │   ├── release.yml       # Docker-Images zu GHCR + GitHub Release bei Tag
│   │   └── sync-wiki.yml     # Spiegelt wiki/ ins GitHub Wiki bei Push auf main
│   └── dependabot.yml        # Dependency-Updates (pip/npm/Actions/Docker)
├── docs/                     # Backup/Restore, Retention- und ISO-Dokumentation
├── wiki/                     # Wiki-Quellen (Markdown) — Sync ins GitHub Wiki via sync-wiki.yml
├── .hooks/pre-commit         # Lokaler Pre-Commit-Hook (ruff + svelte-check)
├── scripts/
│   ├── install.sh            # Linux-Installer (+ systemd-Watchdog)
│   ├── install.ps1           # Windows-Installer
│   ├── backup.sh             # PostgreSQL-Dump + Volumes + Prüfsummen + Retention
│   ├── restore.sh            # Wiederherstellung aus Backup
│   ├── updater-watchdog.sh   # Räumt verwaiste Updater-Container auf
│   ├── deploy.sh             # Einmalige Server-Migration / Notfall-Deploy
│   └── install-hooks.sh      # Installiert .hooks/ in .git/hooks/
├── logo/                     # Logo-, Favicon- und Design-Assets
├── CHANGELOG.md              # Versionshistorie
├── RELEASING.md              # Anleitung zum Schneiden eines Releases
├── SECURITY.md               # Vulnerability-Disclosure-Richtlinie
├── .env.example              # Alle Umgebungsvariablen mit Erklärungen
└── docker-compose.yml        # Compose-Datei für Entwicklung und Produktion (wird vom Installer genutzt)
```

---

## Backend lokal entwickeln (ohne Docker)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

> PostgreSQL/PostGIS und GraphHopper müssen erreichbar sein — am einfachsten weiterhin über Docker Compose.

### Tests ausführen

```bash
cd backend
pytest
```

---

## Frontend prüfen und bauen

```bash
cd frontend
npm install
npm run check
npm run build
```

---

## Datenbankmigrationen

```bash
# Aktuelle Migrationen ausführen
cd backend && alembic upgrade head

# Neue Migration erzeugen
cd backend && alembic revision --autogenerate -m "beschreibung"
```

---

## Nützliche Docker-Befehle

```bash
docker compose up -d --build        # Stack starten
docker compose logs -f backend      # Backend-Logs anzeigen
docker compose logs -f graphhopper  # GraphHopper-Logs anzeigen
docker compose down                 # Services stoppen
docker compose down -v              # inklusive persistenter Daten
```

---

## Pre-Commit-Hook

Der lokale Pre-Commit-Hook (`ruff` + `svelte-check`) lässt sich einmalig installieren:

```bash
./scripts/install-hooks.sh
```

---

## CI und Releases

CI-Checks (Backend-Tests, Frontend-Typecheck, Docker-Build, Dependency-Audit) laufen automatisch auf Push und Pull Requests gegen `main`.

Die Versionierung folgt dem kalenderbasierten Schema **`YYYY.MASTER.FIX`** (z. B. `2026.1.1`): `YYYY` ist die Jahreszahl, `MASTER` das Master-Release (größere Feature-Veröffentlichung innerhalb des Jahres) und `FIX` das Fix-/Beta-Release (Bugfixes, Sicherheits-Patches, Dependabot-Wellen). Das Schema löst die frühere semantische Versionierung ab; das erste Release nach `1.0.2` ist `2026.1.1`.

Für ein neues Release den Tag `vYYYY.MASTER.FIX` (z. B. `v2026.1.1`) setzen — Docker-Images werden dann automatisch zu GHCR gebaut und gepusht; ein GitHub Release wird erstellt. Prerelease-Tags (`vX.Y.Z-beta.N`) bauen zusätzlich `:beta`-Images und ein GitHub-Prerelease, ohne `:latest` zu berühren; jeder Push auf `main` baut außerdem `:nightly`-Images. Vollständige Anleitung in [`RELEASING.md`](https://github.com/RettTechSolutions/ConvoyPlan/blob/main/RELEASING.md).
