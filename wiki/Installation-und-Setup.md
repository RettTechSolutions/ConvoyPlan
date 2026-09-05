# Installation und Setup

Diese Seite beschreibt die Einrichtung von ConvoyPlan für lokale Entwicklung und Produktivbetrieb.

---

## Voraussetzungen

| Komponente | Version | Zweck |
|---|---|---|
| Git | aktuell | Repository klonen |
| Docker + Docker Compose Plugin | aktuell | Alle Dienste starten |
| Node.js + npm | 20+ | Frontend-Entwicklung (lokal) |
| Python | 3.12 | Backend-Entwicklung (lokal, optional) |

---

## Quickstart (Docker)

### 1. Repository klonen

```bash
git clone https://github.com/RettTechSolutions/ConvoyPlan.git
cd ConvoyPlan
```

### 2. Stack starten

```bash
docker compose up -d --build
```

Beim ersten Start lädt GraphHopper die konfigurierte OSM-PBF-Datei herunter und baut den Routing-Graphen. Der Standard ist **DACH** (Deutschland, Österreich, Schweiz, Liechtenstein; ~5,5 GB). Für lokale Tests empfiehlt sich eine kleinere Region:

```yaml
# docker-compose.yml
OSM_DOWNLOAD_URL: https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
OSM_FILENAME: berlin-latest.osm.pbf
```

Logs verfolgen:

```bash
docker compose logs -f graphhopper
```

Gesundheitschecks:

```bash
curl http://localhost:8000/health
curl http://localhost:8989/health
```

### 3. Frontend starten (lokale Entwicklung)

```bash
cd frontend
npm install
npm run dev
```

### 4. Erreichbare Dienste

| Dienst | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| GraphHopper | http://localhost:8989 |

### 5. Setup-Wizard

Beim ersten Start leitet die Anwendung automatisch auf `/setup` weiter. Der fünfstufige Wizard führt durch:

1. **Superadmin-Account** – E-Mail-Adresse und Passwort festlegen.
2. **Erste Organisation** – Org-Name und Org-Code (URL-Slug, 4–8 Zeichen) anlegen; dieser Slug wird Teil aller org-spezifischen URLs (`/o/[slug]/plan/`, `/o/[slug]/admin/`).
3. **Domain und SSL** – Serverdomain (FQDN) eingeben und TLS-Modus wählen:
   - **Let's Encrypt** – automatisches öffentliches Zertifikat
   - **Eigenes Zertifikat** – PEM-Datei hochladen
   - **Intern** – selbstsigniertes Zertifikat für lokale Nutzung
4. **Branding** (optional) – App-Name, Farben und Logo anpassen. Überspringbar und später im Admin-Bereich erreichbar.
5. **Abschluss** – Caddy wird live neu geladen, danach direkt zur Anmeldung unter `https://<DOMAIN>/o/[slug]/login`.

> Für lokale Entwicklung ohne Caddy: `localhost` als Domain und `internal` als TLS-Modus wählen.

---

## Konfiguration

Eine vollständige Vorlage liegt in `.env.example`. Die wichtigsten Variablen:

### Datenbank

| Variable | Beschreibung |
|---|---|
| `POSTGRES_USER` | Datenbankbenutzer |
| `POSTGRES_PASSWORD` | Datenbankpasswort – in Produktion zwingend ändern |
| `POSTGRES_DB` | Datenbankname |

### Backend

| Variable | Standard | Beschreibung |
|---|---|---|
| `DATABASE_URL` | *(aus POSTGRES_\* zusammengesetzt)* | PostgreSQL/PostGIS-Verbindung |
| `APP_ENV` | `production` | `production` erzwingt einen starken `JWT_SECRET` (Fail-Closed); `development` lockert die Prüfung für lokale Arbeit |
| `JWT_SECRET` | *(kein sicherer Default)* | Signaturschlüssel für JWTs – in Produktion zwingend ≥ 32 Zeichen; sonst **startet das Backend nicht** |
| `JWT_ALGORITHM` | `HS256` | JWT-Algorithmus |
| `JWT_EXPIRE_MINUTES` | `10080` | Token-Ablaufzeit in Minuten (7 Tage) |
| `GRAPHHOPPER_URL` | `http://graphhopper:8989` | URL der Routing-Engine |
| `APP_BASE_URL` | `https://convoyplan.example.com` | Öffentliche App-Origin (Fallback für CORS in Produktion) |
| `CORS_ORIGINS` | *(leer)* | Komma-getrennte Allowlist oder `*`; leer = App-Origin aus `APP_BASE_URL`. `*` nur in Entwicklung |

Sicheren JWT-Secret generieren (die Installer tun das automatisch):

```bash
openssl rand -hex 32
```

> ⚠️ In Produktion (`APP_ENV=production`, Default) verweigert das Backend den Start, wenn `JWT_SECRET` leer, der Platzhalter oder kürzer als 32 Zeichen ist (Fail-Closed).

### SSL / Caddy

| Variable | Beschreibung |
|---|---|
| `DOMAIN` | Serverdomain (z. B. `convoy.example.com`), Standard: `localhost` |
| `ACME_EMAIL` | E-Mail für Let's Encrypt |
| `CADDY_TLS_CERT` | Pfad zum PEM-Zertifikat (optional, für eigene Zertifikate) |
| `CADDY_TLS_KEY` | Pfad zum PEM-Schlüssel (optional, für eigene Zertifikate) |
| `HTTP_PORT` | Externer HTTP-Port, Standard: `80` |
| `HTTPS_PORT` | Externer HTTPS-Port, Standard: `443` |

### GraphHopper

| Variable | Standard | Beschreibung |
|---|---|---|
| `OSM_DOWNLOAD_URL` | `https://download.geofabrik.de/europe/dach-latest.osm.pbf` | Download-URL der OSM-PBF-Datei |
| `OSM_FILENAME` | `dach-latest.osm.pbf` | Dateiname im persistenten OSM-Volume |
| `JAVA_OPTS` | `-Xmx8g -Xms1g -XX:+UseG1GC` | JVM-Speicherkonfiguration |

> Richtwerte: DACH `-Xmx8g`, Deutschland `-Xmx6g`, Bayern `-Xmx3g`, Berlin `-Xmx1g`.

> **Regionswechsel:** Die Variablen hier gelten nur für den **Erststart**. Zum
> Wechseln der Kartenregion im laufenden Betrieb gibt es seit `2026.4.0` die
> Karte „Kartenregion" im Admin-Panel unter **System** — dort mit
> Vorabschätzung von Speicher-, Platten- und Zeitbedarf, Live-Fortschritt und
> ohne nennenswerten Routing-Ausfall (der neue Graph entsteht neben dem
> laufenden). Seit `2026.5.0` lassen sich dort auch **mehrere** Regionen
> gleichzeitig wählen; sie werden zu einer Karte zusammengeführt, sodass
> Routen über die Ländergrenzen hinweg funktionieren.
>
> Die aktive Region liegt danach in `/data/osm/.region` im `osm_data`-Volume
> und hat Vorrang vor den Variablen aus der `.env` — so überlebt sie ein
> `docker compose up`. Wer die Variablen hier nachträglich ändert, ändert
> deshalb **nichts** an einer bereits per Panel gewechselten Installation.
>
> Der Umriss auf der Karte kommt dagegen aus
> `frontend/static/geo/dach.geojson` und passt sich **nicht** automatisch an;
> wer dauerhaft eine andere Region fährt, tauscht diese Datei mit (siehe
> `frontend/static/geo/README.md`).

### Sicherheit und Datenschutz

| Variable | Standard | Beschreibung |
|---|---|---|
| `MFA_ENCRYPTION_KEY` | *(aus `JWT_SECRET` abgeleitet)* | Fernet-Schlüssel zur Verschlüsselung der TOTP-Secrets at-rest. Rotation von `JWT_SECRET` macht ohne eigenen Schlüssel bestehende MFA-Secrets unlesbar |
| `PASSWORD_BREACH_CHECK_ENABLED` | `true` | Abgleich neuer Passwörter gegen Have-I-Been-Pwned (k-Anonymity, fail-open). Für Air-Gapped-Setups auf `false` |
| `CSP_ENFORCE` | `false` | Content-Security-Policy erzwingen (Default: Report-Only, bricht die UI nicht) |
| `QUOTA_ROUTING_PER_HOUR` | `240` | Stundenbudget für Routenberechnungen (GraphHopper) je angemeldetem Benutzer. `0` = Drossel aus |
| `QUOTA_ROUTING_DEMO_PER_HOUR` | `40` | Dasselbe für Demo-Sitzungen (zusätzlich pro IP gezählt) |
| `QUOTA_GEOCODE_PER_HOUR` | `600` | Stundenbudget für die Adresssuche (HERE/Photon) je Benutzer |
| `QUOTA_GEOCODE_DEMO_PER_HOUR` | `100` | Dasselbe für Demo-Sitzungen |
| `QUOTA_TRAFFIC_PER_HOUR` | `600` | Stundenbudget für die Live-Verkehrslage (HERE/TomTom) je Benutzer |
| `QUOTA_TRAFFIC_DEMO_PER_HOUR` | `100` | Dasselbe für Demo-Sitzungen |
| `RETENTION_ENABLED` | `true` | Periodisches Purgen alter Daten durch den `retention`-Container |
| `RETENTION_INTERVAL` | `3600` | Sekunden zwischen den Purge-Läufen |
| `RETENTION_POSITIONS_HOURS` | `24` | Live-Positionen älter als dieser Wert werden gelöscht |
| `RETENTION_AUDIT_DAYS` | `365` | Audit-Log-Einträge älter als dieser Wert werden gelöscht |
| `RETENTION_SHARE_LINKS_DAYS` | `30` | Widerrufene Share-Links älter als dieser Wert werden gelöscht |
| `BACKUP_DIR` | `./backups` | Zielverzeichnis für `scripts/backup.sh` |
| `BACKUP_RETENTION_DAYS` | `30` | Aufbewahrungsdauer der Backups |

> Details zu Härtung, Audit-Log, DSGVO und Backup/Restore: **[Sicherheit und Datenschutz](Sicherheit-und-Datenschutz)**.

### Lizenz und Auto-Updater

| Variable | Beschreibung |
|---|---|
| `LICENSE_KEY` | Lizenzschlüssel. Ohne gültigen Schlüssel läuft die App im Demo-Modus. Alternativ über den Admin-Bereich eintragbar (wird dann in der DB gespeichert). |
| `GITHUB_TOKEN` | GitHub PAT mit `repo`-Leseberechtigung. Benötigt für den Auto-Updater, um neue Commits/Releases zu erkennen. |
| `GITHUB_REPO` | Repository, das der Auto-Updater überwacht. Standard: `RettTechSolutions/ConvoyPlan`. |
| `UPDATE_CHANNEL` | Fallback-Kanal: `stable` (Standard), `beta` oder `nightly`. Der Schalter im Admin-Bereich überschreibt diesen Wert. |
| `UPDATE_MODE` | Fallback-Modus: `auto` (Standard) oder `notify`. Der Schalter im Admin-Bereich überschreibt diesen Wert. |
| `UPDATE_NOTIFY_ON_AUTO` | Nur bei `auto`: `true` schickt zusätzlich eine E-Mail an Superadmins nach automatischer Installation (Standard: `false`). |
| `UPDATE_NOTIFY_INTERVAL` | Prüfintervall in Sekunden für fällige Update-Benachrichtigungen (Standard: `1800`). |

> Details: **[Auto-Updater](Auto-Updater)** und **[Lizenz und Demo-Modus](Lizenz-und-Demo-Modus)**.

### Verkehrsdaten

| Variable | Beschreibung |
|---|---|
| `HERE_TRAFFIC_API_KEY` / `TOMTOM_TRAFFIC_API_KEY` | Optionale API-Keys für die Live-Verkehrslage. Ohne Key bleibt die Funktion inaktiv. Alternativ im Admin-Bereich hinterlegbar (hat Vorrang). |
| `TRAFFIC_FLOW_PROVIDER` | Anbieter erzwingen (`here`/`tomtom`). Standard: automatisch, HERE bevorzugt. |
| `HERE_API_KEY` | Optional. Aktiviert die Adresssuche im Plan-Editor über HERE Geocoding & Search (serverseitig proxied). Leer = `HERE_TRAFFIC_API_KEY` mitbenutzen bzw. Photon-Fallback. |
| `HERE_MONTHLY_LIMIT` | Kostendeckel für die Adresssuche: max. HERE-Anfragen pro Kalendermonat (Standard `25000`, `0` = kein App-Deckel). Deckel erreicht → automatischer Photon-Fallback. |
| `OPENDATA_TRAFFIC_ENABLED` | Offene Baustellen-/Sperrungsfeeds aktiviert lassen. Standard: `true`. |
| `OPENDATA_TRAFFIC_FEEDS` | Kommaseparierte Liste `format\|url`. Formate: `mobidata_bw`, `berlin_viz`, `datex2`. |
| `OPENDATA_TRAFFIC_CLIENT_CERT` | Client-Zertifikat (PEM) für per mTLS geschützte `datex2`-Feeds (mobilithek). |
| `OPENDATA_TRAFFIC_CA_CERT` | Nur für Broker mit **privater** CA. Für den mobilithek-Broker **leer lassen**. |

> Schritt-für-Schritt-Anleitung: **[Verkehrsdaten](Verkehrsdaten)**.

### Frontend (lokale Entwicklung)

```env
# frontend/.env.local
VITE_WS_HOST=localhost:8000
```

---

## GraphHopper-Cache erneuern

Nach einer Änderung der OSM-Region muss der Graph-Cache neu aufgebaut werden:

```bash
docker compose down
docker volume rm convoyplan_gh_graph
docker compose up -d --build
```

---

## Deployment (Produktion)

### Docker Compose

```bash
# 1. Umgebungsvariablen anpassen
cp .env.example .env
# JWT_SECRET, POSTGRES_PASSWORD, DOMAIN, ACME_EMAIL setzen

# 2. Stack starten
docker compose -f docker-compose.yml up -d --build

# 3. Setup-Wizard aufrufen
open https://<DOMAIN>/setup
```

### Portainer

Für die Produktion wird dieselbe `docker-compose.yml` verwendet. Sie kann vorgefertigte Images aus der GitHub Container Registry (GHCR) statt lokaler Builds nutzen — kein `git clone` auf dem Server nötig. Pflichtvariablen beim Anlegen des Stacks:

| Variable | Beispiel |
|---|---|
| `BACKEND_IMAGE` | `ghcr.io/retttechsolutions/convoyplan-backend:latest` |
| `FRONTEND_IMAGE` | `ghcr.io/retttechsolutions/convoyplan-frontend:latest` |
| `GRAPHHOPPER_IMAGE` | `ghcr.io/retttechsolutions/convoyplan-graphhopper:latest` |
| `JWT_SECRET` | mit `openssl rand -hex 32` erzeugen |
| `POSTGRES_PASSWORD` | sicheres Datenbankpasswort |
| `DOMAIN` / `ACME_EMAIL` | FQDN bzw. E-Mail für Let's Encrypt |

Der Setup-Wizard übernimmt die Erstkonfiguration nach dem ersten Stack-Start.

> **Hinweis:** Der `updater`-Container ist nur in `docker-compose.yml` enthalten. In Portainer übernimmt der Stack-Update-Mechanismus von Portainer selbst das Deployment neuer Images.

### Checkliste für Produktion

- [ ] `JWT_SECRET` mit `openssl rand -hex 32` generieren – nicht in Git versionieren
- [ ] Datenbankpasswort ändern
- [ ] `CORS_ORIGINS` auf die produktive Domain einschränken
- [ ] Persistente Volumes (`postgres_data`, `caddy_data`, `cert_uploads`, `logo_uploads`) regelmäßig sichern
- [ ] Für DACH genug RAM einplanen (`JAVA_OPTS=-Xmx8g`; nur Deutschland: `-Xmx6g`)
- [ ] GraphHopper-Graph-Cache (`gh_graph`) auf schnellem Speicher ablegen
- [ ] `GITHUB_TOKEN` setzen, damit der Auto-Updater Commit-Stände abrufen kann
- [ ] Lizenzschlüssel setzen (Env oder Admin → System); sonst läuft die Instanz dauerhaft im Demo-Modus

---

## Lokale Backend-Entwicklung (ohne Docker)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

> PostgreSQL/PostGIS und GraphHopper müssen erreichbar sein – am einfachsten weiterhin über Docker Compose.

### Tests ausführen

```bash
cd backend
pytest
```

### Frontend prüfen und bauen

```bash
cd frontend
npm install
npm run check
npm run build
```

### Datenbankmigrationen

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
docker compose down -v              # Services stoppen inkl. persistenter Daten
```

---

## Native App / PWA

Das Frontend ist als Progressive Web App konfiguriert und kann im Browser installiert werden. Für native Apps ist Capacitor vorbereitet:

```bash
cd frontend
npm run build
npx cap add android   # einmalig, alternativ: ios
npx cap sync
npx cap open android
```

> Für iOS wird eine macOS-Umgebung mit Xcode benötigt.

---

## CI und Releases

CI-Checks (Backend-Tests, Frontend-Typecheck, Docker-Build) laufen automatisch auf Push und Pull Requests gegen `main`.

Für ein neues Release den Tag `vX.Y.Z` setzen – Docker-Images werden dann automatisch zu GHCR gebaut und gepusht und ein GitHub Release wird erstellt. Seit `2026.1.1` folgt die Versionsnummer dem kalenderbasierten Schema `YYYY.MASTER.FIX` (Jahr.Master-Release.Fix-Release) statt SemVer. Prerelease-Tags (`vX.Y.Z-beta.N`) bauen zusätzlich `:beta`-Images und ein GitHub-Prerelease, ohne `:latest` zu berühren; jeder Push auf `main` baut außerdem `:nightly`-Images.

---

## Sicherheitshinweise

- In Produktion (`APP_ENV=production`, Default) verweigert das Backend den Start, wenn `JWT_SECRET` leer, der Platzhalter oder kürzer als 32 Zeichen ist (Fail-Closed) — mit `openssl rand -hex 32` erzeugen.
- Die Datenbankzugänge in `docker-compose.yml` sind Entwicklungs-Defaults – in Produktion ändern.
- Die Caddy-Admin-API läuft auf Port `:2019` und ist nur im Docker-Netzwerk intern erreichbar.
- Caddy liefert Security-Header (HSTS, `X-Content-Type-Options`, `X-Frame-Options` u. a.) und eine Content-Security-Policy aus (Report-Only, per `CSP_ENFORCE=true` erzwingbar).
- Die persistierte Caddyfile (`/certs/Caddyfile`, vom Setup-Wizard geschrieben) wird bei jedem Backend-Start gegen die aktuelle Header-Baseline geprüft und bei Bedarf aus den gespeicherten Setup-Werten neu erzeugt und live nachgeladen — Bestandsinstallationen aus der Zeit vor den Security-Headern liefern sie damit automatisch aus, ohne erneuten Setup-Durchlauf.
- Endpunkte, die fremdes Kontingent kosten (Routing, Adresssuche, Verkehrslage), haben ein Stundenbudget je Aufrufer; Demo-Sitzungen bekommen das kleinere und werden zusätzlich pro IP gezählt (`QUOTA_*`).
- TOTP-Secrets werden Fernet-verschlüsselt at-rest gespeichert; Passwort-/MFA-Reset entziehen über die `token_version` alle bestehenden JWTs.
- Öffentliche Share-Links sind ohne Login abrufbar – Tokens sollten wie vertrauliche Links behandelt und bei Bedarf widerrufen werden.
- Live-Tracking verarbeitet Standortdaten – Aufbewahrung wird über den `retention`-Container geregelt.

> Vollständige Übersicht: **[Sicherheit und Datenschutz](Sicherheit-und-Datenschutz)**.
