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

Beim ersten Start lädt GraphHopper die konfigurierte OSM-PBF-Datei herunter und baut den Routing-Graphen. Der Standard ist Deutschland (~4 GB). Für lokale Tests empfiehlt sich eine kleinere Region:

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

Beim ersten Start leitet die Anwendung automatisch auf `/setup` weiter. Der dreistufige Wizard führt durch:

1. **Superadmin-Account** – E-Mail-Adresse und Passwort festlegen.
2. **Domain und SSL** – Serverdomain (FQDN) eingeben und TLS-Modus wählen:
   - **Let's Encrypt** – automatisches öffentliches Zertifikat
   - **Eigenes Zertifikat** – PEM-Datei hochladen
   - **Intern** – selbstsigniertes Zertifikat für lokale Nutzung
3. **Abschluss** – Caddy wird live neu geladen, danach direkt zur Anmeldung.

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
| `JWT_SECRET` | `changeme-in-production` | Signaturschlüssel für JWTs – zwingend ersetzen |
| `JWT_ALGORITHM` | `HS256` | JWT-Algorithmus |
| `JWT_EXPIRE_MINUTES` | `10080` | Token-Ablaufzeit in Minuten (7 Tage) |
| `GRAPHHOPPER_URL` | `http://graphhopper:8989` | URL der Routing-Engine |
| `CORS_ORIGINS` | `*` | Erlaubte CORS-Origins – in Produktion einschränken |

Sicheren JWT-Secret generieren:

```bash
openssl rand -hex 32
```

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
| `OSM_DOWNLOAD_URL` | `https://download.geofabrik.de/europe/germany-latest.osm.pbf` | Download-URL der OSM-PBF-Datei |
| `OSM_FILENAME` | `germany-latest.osm.pbf` | Dateiname im persistenten OSM-Volume |
| `JAVA_OPTS` | `-Xmx2g -Xms512m -XX:+UseG1GC` | JVM-Speicherkonfiguration |

> Für große Regionen (Deutschland ~4 GB) mindestens `-Xmx4g` empfohlen.

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

Eine fertige Stack-Konfiguration liegt in `portainer-stack.yml`. Images werden über Variablen gesetzt; der Setup-Wizard übernimmt die Erstkonfiguration.

### Checkliste für Produktion

- [ ] `JWT_SECRET` mit `openssl rand -hex 32` generieren – nicht in Git versionieren
- [ ] Datenbankpasswort ändern
- [ ] `CORS_ORIGINS` auf die produktive Domain einschränken
- [ ] Persistente Volumes (`postgres_data`, `caddy_data`, `cert_uploads`) regelmäßig sichern
- [ ] Für Deutschland genug RAM einplanen (`JAVA_OPTS=-Xmx4g`)
- [ ] GraphHopper-Graph-Cache (`gh_graph`) auf schnellem Speicher ablegen

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

Für ein neues Release den Tag `vX.Y.Z` setzen – Docker-Images werden dann automatisch zu GHCR gebaut und gepusht und ein GitHub Release wird erstellt.

---

## Sicherheitshinweise

- Der Standardwert `changeme-in-production` für `JWT_SECRET` ist **nur für lokale Entwicklung** gedacht.
- Die Datenbankzugänge in `docker-compose.yml` sind Entwicklungs-Defaults – in Produktion ändern.
- Die Caddy-Admin-API läuft auf Port `:2019` und ist nur im Docker-Netzwerk intern erreichbar.
- Öffentliche Share-Links sind ohne Login abrufbar – Tokens sollten wie vertrauliche Links behandelt werden.
- Live-Tracking verarbeitet Standortdaten – Zugriff, Aufbewahrung und Löschung organisatorisch regeln.
