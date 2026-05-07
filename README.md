<p align="center">
  <img src="logo/Logo%20Horizontal.png" alt="MarschPlan Logo" width="420">
</p>

# MarschPlan

**MarschPlan ist eine browserbasierte Planungssoftware für Marschverbände, Konvois und Einsatzfahrten von BOS-Organisationen.**

Die Anwendung unterstützt Planerinnen und Planer dabei, Fahrzeuge zu verwalten, Marschrouten auf Basis von OpenStreetMap zu erstellen, Wegpunkte und technische Halte zu strukturieren, Zeitpläne automatisch zu berechnen und Marschbefehle als PDF, GPX oder JSON zu exportieren. Live-Tracking, Wetterdaten, Sperrungsinformationen und GeoJSON-Lagedaten machen MarschPlan zu einer zentralen Lage- und Planungsoberfläche für Übungen, Einsätze und Verlegungen.

---

## Inhaltsverzeichnis

- [Highlights](#highlights)
- [Funktionsumfang](#funktionsumfang)
- [Screenshots und Assets](#screenshots-und-assets)
- [Architektur](#architektur)
- [Tech-Stack](#tech-stack)
- [Projektstruktur](#projektstruktur)
- [Quickstart](#quickstart)
- [Konfiguration](#konfiguration)
- [API-Übersicht](#api-übersicht)
- [Datenmodell](#datenmodell)
- [Entwicklung](#entwicklung)
- [Deployment](#deployment)
- [Native App / PWA](#native-app--pwa)
- [Sicherheitshinweise](#sicherheitshinweise)
- [Roadmap-Ideen](#roadmap-ideen)
- [Lizenz](#lizenz)

---

## Highlights

- **Kartenbasierte Marschplanung** mit OpenStreetMap und MapLibre GL.
- **Routing über GraphHopper** inklusive selbst gehosteter Routing-Engine im Docker-Setup.
- **Fahrzeugverwaltung** mit Funkrufname, Kennzeichen, Abmessungen, Gewicht, Rolle und Kraftstoffdaten.
- **Wegpunkte, Kontrollpunkte und technische Halte** inklusive Haltezeiten und Zweck wie Tanken, Pause oder Wartung.
- **Automatische Zeitplanung** anhand von Startzeit, Marschgeschwindigkeiten und Halten.
- **Marschbefehl-PDF** sowie GPX- und JSON-Export für Weitergabe und Nachbearbeitung.
- **Live-Tracking per WebSocket** mit Browser-Geolocation und Fahrzeugstatus.
- **Organisations- und Rollenmodell** für Admins, Planer, Fahrer und Beobachter.
- **Wetter- und Overpass-Integration** für Wetterdaten, Sperrungen und Baustellen.
- **PWA und Capacitor-Konfiguration** für installierbare Web-App und native App-Wrapper.

---

## Funktionsumfang

### Planung und Routing

| Funktion | Beschreibung | Status |
|---|---|---:|
| Karte | Interaktive OSM-Karte mit Planungsansicht | ✅ |
| Wegpunkte | Start, Ziel, Wegpunkte, Kontrollpunkte und technische Halte | ✅ |
| Routenberechnung | GraphHopper-Routing über selbst gehosteten Dienst | ✅ |
| Zeitplan | Automatische Ankunfts- und Abfahrtszeiten | ✅ |
| Marschgeschwindigkeiten | Separate innerörtliche und außerörtliche Geschwindigkeit | ✅ |
| Kraftstoffplanung | Fahrzeugdaten und Tankstellenabfrage entlang der Route | ✅ |

### Verwaltung und Zusammenarbeit

| Funktion | Beschreibung | Status |
|---|---|---:|
| Login | Registrierung und JWT-basierte Authentifizierung | ✅ |
| Fahrzeuge | CRUD für Einsatzfahrzeuge und Konvoirollen | ✅ |
| Marschverbände | CRUD für Konvois und zugeordnete Fahrzeuge | ✅ |
| Teilverbände | Sub-Convoys mit Parent-Konvoi | ✅ |
| Mandanten | Organisationen mit Mitgliederverwaltung | ✅ |
| Rollen | Admin, Planer, Fahrer und Beobachter | ✅ |
| Freigabelink | Öffentliche Routenansicht per Share-Token | ✅ |

### Live, Lage und Export

| Funktion | Beschreibung | Status |
|---|---|---:|
| Live-Tracking | Positionsupdates per REST und WebSocket | ✅ |
| Fahrzeugstatus | Geplant, unterwegs, angekommen oder verspätet | ✅ |
| Wetter | Integration über Open-Meteo ohne API-Key | ✅ |
| Sperrungen | Abfrage von OSM-Daten über Overpass API | ✅ |
| Lagedaten | GeoJSON-Layer hochladen, anzeigen und verwalten | ✅ |
| PDF | Marschbefehl als PDF | ✅ |
| GPX / JSON | Export für Navigation, Dokumentation und Weiterverarbeitung | ✅ |
| PWA | Installierbare Web-App mit Tile-Caching | ✅ |
| Native Wrapper | Capacitor-Konfiguration für Android und iOS | ✅ |

---

## Screenshots und Assets

Im Repository liegen bereits Logo- und Design-Assets unter [`logo/`](logo/):

| Asset | Datei |
|---|---|
| Hauptlogo | `logo/Hauptlogo.svg` / `logo/Hauptlogo.png` |
| Horizontales Logo | `logo/Logo Horizontal.svg` / `logo/Logo Horizontal.png` |
| Favicon | `logo/Favicon.svg` / `logo/Favicon.png` |
| Designgrafik | `logo/ConvoyPlan_Design.png` |

> Tipp für GitHub: Screenshots der Planungsansicht, Tracking-Ansicht und PDF-Ausgabe können später in `docs/screenshots/` abgelegt und hier eingebunden werden.

---

## Architektur

MarschPlan besteht aus vier Kernbausteinen:

```mermaid
flowchart LR
    Browser[Browser / PWA / Capacitor App]
    Frontend[SvelteKit Frontend]
    API[FastAPI Backend]
    DB[(PostgreSQL + PostGIS)]
    GH[GraphHopper]
    EXT[Open-Meteo / Overpass]

    Browser --> Frontend
    Frontend -->|REST + WebSocket| API
    API --> DB
    API --> GH
    API --> EXT
```

- Das **Frontend** stellt Login, Planung, Karte, Live-Tracking und öffentliche Freigabelinks bereit.
- Das **Backend** bündelt Authentifizierung, Geschäftslogik, Routing-Aufbereitung, Exporte und Integrationen.
- **PostgreSQL mit PostGIS** speichert Nutzer, Fahrzeuge, Konvois, Geometrien, Positionen und Lagedaten.
- **GraphHopper** läuft selbst gehostet und verarbeitet beim ersten Start die gewählte OSM-PBF-Datei.

---

## Tech-Stack

| Schicht | Technologie |
|---|---|
| Frontend | SvelteKit, Svelte 5, TypeScript, Vite |
| Karte | MapLibre GL, OpenStreetMap |
| PWA | `@vite-pwa/sveltekit`, Workbox |
| Native App | Capacitor-Konfiguration |
| Backend | Python 3.12, FastAPI, Uvicorn |
| Datenbank | PostgreSQL 15, PostGIS |
| ORM / Migrationen | SQLAlchemy Async, Alembic |
| Authentifizierung | JWT, `python-jose`, `passlib` |
| Routing | GraphHopper 9.1 |
| Geodaten | GeoAlchemy2, Shapely, GeoJSON |
| Exporte | GPXPy, fpdf2, JSON |
| Externe Daten | Open-Meteo, OpenStreetMap Overpass API |
| Infrastruktur | Docker Compose, Portainer Stack |

---

## Projektstruktur

```text
MarschPlan/
├── backend/
│   ├── app/
│   │   ├── api/routes/       # REST- und WebSocket-Endpunkte
│   │   ├── models/           # SQLAlchemy-Modelle
│   │   ├── schemas/          # Pydantic-Schemas
│   │   ├── services/         # Routing, Zeitplan, Export, Wetter, Tracking
│   │   ├── config.py         # Backend-Konfiguration über Umgebungsvariablen
│   │   ├── database.py       # Async-Datenbankanbindung
│   │   └── main.py           # FastAPI-App und Router-Registrierung
│   ├── alembic/              # Datenbankmigrationen
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/lib/api/          # API-Client
│   ├── src/lib/components/   # Karte, Wetter, Lagedatenpanel
│   ├── src/lib/stores/       # Auth-, Karten-, Konvoi-, Tracking-Stores
│   ├── src/routes/           # Login, Planung, Tracking, Share-Ansicht
│   ├── capacitor.config.ts
│   ├── package.json
│   └── vite.config.ts
├── graphhopper/
│   ├── Dockerfile
│   ├── entrypoint.sh         # OSM-Download und GraphHopper-Start
│   └── config.yml
├── logo/                     # Logo-, Favicon- und Design-Assets
├── docker-compose.yml        # Lokales Entwicklungssetup
└── portainer-stack.yml       # Beispielstack für Portainer/Serverbetrieb
```

---

## Quickstart

### Voraussetzungen

- Git
- Docker und Docker Compose Plugin
- Node.js 20+ und npm für das Frontend
- Optional: Python 3.12 für lokale Backend-Entwicklung ohne Container

### 1. Repository klonen

```bash
git clone https://github.com/RettTechSolutions/MarschPlan.git
cd MarschPlan
```

### 2. Backend, Datenbank und GraphHopper starten

```bash
docker compose up -d --build
```

Beim ersten Start lädt GraphHopper die konfigurierte OSM-PBF-Datei herunter und baut daraus den Routing-Graphen. Der Standard ist Deutschland und kann mehrere Gigabyte groß sein. Für schnelle lokale Tests empfiehlt sich eine kleinere Region wie Berlin.

Logs verfolgen:

```bash
docker compose logs -f graphhopper
```

Gesundheitschecks prüfen:

```bash
curl http://localhost:8000/health
curl http://localhost:8989/health
```

### 3. Kleinere Testregion konfigurieren

Für einen schnelleren Start kann in `docker-compose.yml` beispielsweise Berlin gesetzt werden:

```yaml
OSM_DOWNLOAD_URL: https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
OSM_FILENAME: berlin-latest.osm.pbf
```

Nach einer Änderung der OSM-Datei sollte der GraphHopper-Graph-Cache neu aufgebaut werden:

```bash
docker compose down
docker volume rm marschplan_gh_graph
docker compose up -d --build
```

### 4. Frontend starten

```bash
cd frontend
npm install
npm run dev
```

Die Anwendung ist anschließend erreichbar unter:

- Frontend: <http://localhost:5173>
- Backend API: <http://localhost:8000>
- Swagger UI: <http://localhost:8000/docs>
- GraphHopper: <http://localhost:8989>

### 5. Ersten Account anlegen

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"pilot@bos.de","password":"sicheres-passwort"}'
```

Login per API:

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"pilot@bos.de","password":"sicheres-passwort"}'
```

---

## Konfiguration

### Backend

| Variable | Standard | Beschreibung |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://marschplan:marschplan@localhost:5432/marschplan` | PostgreSQL/PostGIS-Verbindung |
| `JWT_SECRET` | `changeme-in-production` | Signaturschlüssel für JWTs; in Produktion zwingend ändern |
| `JWT_ALGORITHM` | `HS256` | JWT-Algorithmus |
| `JWT_EXPIRE_MINUTES` | `10080` | Ablaufzeit eines Tokens in Minuten |
| `GRAPHHOPPER_URL` | `http://localhost:8989` | URL der Routing-Engine |

### Frontend

| Variable | Standard | Beschreibung |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000` | Basis-URL des Backends für REST-Aufrufe |

Beispiel für `frontend/.env.local`:

```env
VITE_API_URL=http://localhost:8000
```

### GraphHopper

| Variable | Standard | Beschreibung |
|---|---|---|
| `OSM_DOWNLOAD_URL` | `https://download.geofabrik.de/europe/germany-latest.osm.pbf` | Download-URL der OSM-PBF-Datei |
| `OSM_FILENAME` | `germany-latest.osm.pbf` | Dateiname im persistenten OSM-Volume |
| `JAVA_OPTS` | `-Xmx2g -Xms512m -XX:+UseG1GC` | JVM-Speicherkonfiguration |

---

## API-Übersicht

Die vollständige OpenAPI-Dokumentation wird automatisch von FastAPI bereitgestellt:

- Swagger UI: <http://localhost:8000/docs>
- OpenAPI JSON: <http://localhost:8000/openapi.json>

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `POST` | `/api/auth/register` | Account erstellen |
| `POST` | `/api/auth/login` | Login und JWT erhalten |
| `GET/POST/PUT/DELETE` | `/api/vehicles/` | Fahrzeuge verwalten |
| `GET/POST/PUT/DELETE` | `/api/convoys/` | Marschverbände verwalten |
| `POST/DELETE` | `/api/convoys/{convoy_id}/vehicles` | Fahrzeuge einem Konvoi zuordnen oder entfernen |
| `GET/POST/PUT/DELETE` | `/api/convoys/{convoy_id}/waypoints` | Wegpunkte verwalten |
| `GET/POST` | `/api/convoys/{convoy_id}/sub-convoys` | Teilverbände anzeigen oder erstellen |
| `POST` | `/api/convoys/{convoy_id}/calculate-route` | Route und Zeitplan berechnen |
| `GET` | `/api/convoys/{convoy_id}/export/gpx` | GPX exportieren |
| `GET` | `/api/convoys/{convoy_id}/export/json` | JSON exportieren |
| `GET` | `/api/convoys/{convoy_id}/export/pdf` | Marschbefehl als PDF exportieren |
| `GET` | `/api/convoys/{convoy_id}/fuel-stations` | Tankstellen entlang der Route abrufen |
| `GET` | `/api/convoys/share/{token}` | Öffentliche Routenansicht abrufen |
| `GET/POST/DELETE` | `/api/organizations/` | Organisationen und Mitglieder verwalten |
| `GET/POST` | `/api/convoys/{convoy_id}/positions` | Live-Positionen abrufen oder aktualisieren |
| `PATCH` | `/api/convoys/{convoy_id}/vehicles/{vehicle_id}/status` | Fahrzeugstatus ändern |
| `WS` | `/api/ws/tracking/{convoy_id}?token=...` | WebSocket für Live-Tracking |
| `GET/POST/PUT/DELETE` | `/api/convoys/{convoy_id}/lage` | GeoJSON-Lagedaten verwalten |
| `GET` | `/api/weather/?lat=...&lon=...` | Wetterdaten abrufen |
| `GET` | `/api/overpass/closures?lat=...&lon=...` | Sperrungen und Baustellen abrufen |

---

## Datenmodell

```text
User
├── Vehicles
├── Convoys
└── UserOrganizations

Organization
└── UserOrganizations

Convoy
├── parent_convoy_id        # Teilverband / Sub-Convoy
├── organization_id         # Mandant / Organisation
├── ConvoyVehicles          # Fahrzeugzuordnung inkl. Status
├── Waypoints               # Wegpunkte, Kontrollpunkte, technische Halte
├── Route                   # Liniengeometrie, Distanz, Dauer, GPX
├── VehiclePositions        # Live-Tracking-Positionen
└── LageLayers              # GeoJSON-Lagedaten
```

Wichtige fachliche Objekte:

- **User**: Account für Login und Besitz von Fahrzeugen/Konvois.
- **Organization**: Mandant für organisationsbezogene Planung und Rollen.
- **Vehicle**: Fahrzeug mit Funkrufname, Kennzeichen, Abmessungen, Gewicht und Kraftstoffdaten.
- **Convoy**: Marschverband mit Start-/Zielpunkt, Marschbefehl-Feldern, Share-Token und Status.
- **Waypoint**: Wegpunkt, Stopp, Kontrollpunkt oder technischer Halt mit Zeitplanung.
- **Route**: Berechnete Route inklusive Geometrie, Distanz, Dauer und Exportdaten.
- **VehiclePosition**: Aktuelle Fahrzeugposition innerhalb eines Konvois.
- **LageLayer**: Zusätzliche GeoJSON-Lageinformationen.

---

## Entwicklung

### Backend lokal entwickeln

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

> Hinweis: Für lokale Backend-Entwicklung müssen PostgreSQL/PostGIS und GraphHopper erreichbar sein. Am einfachsten laufen diese weiterhin über Docker Compose.

### Frontend prüfen und bauen

```bash
cd frontend
npm install
npm run check
npm run build
```

### Datenbankmigrationen

Aktuelle Migrationen ausführen:

```bash
cd backend
alembic upgrade head
```

Neue Migration erzeugen:

```bash
cd backend
alembic revision --autogenerate -m "beschreibung"
```

### Nützliche Docker-Befehle

```bash
# Stack starten
docker compose up -d --build

# Logs anzeigen
docker compose logs -f backend

# Services stoppen
docker compose down

# Persistente Daten inklusive OSM-/GraphHopper-Cache entfernen
docker compose down -v
```

---

## Deployment

Für Server- oder Portainer-Setups liegt eine Beispielkonfiguration in `portainer-stack.yml` bereit. Dort werden Images über Variablen konfiguriert:

| Variable | Zweck |
|---|---|
| `BACKEND_IMAGE` | Backend-Image für den produktiven Stack |
| `GRAPHHOPPER_IMAGE` | GraphHopper-Image für den produktiven Stack |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Datenbankzugang |
| `JWT_SECRET` | Produktiver JWT-Schlüssel |
| `DB_PORT`, `BACKEND_PORT`, `GH_PORT` | Externe Ports |
| `OSM_DOWNLOAD_URL`, `OSM_FILENAME`, `JAVA_OPTS` | GraphHopper-Konfiguration |

Empfehlungen für Produktion:

1. `JWT_SECRET` durch einen langen, zufälligen Wert ersetzen.
2. Datenbankpasswort ändern und nicht öffentlich versionieren.
3. API nur über HTTPS bereitstellen.
4. CORS-Origins im Backend auf die produktive Domain einschränken.
5. Persistente Volumes regelmäßig sichern.
6. Für große OSM-Regionen ausreichend RAM und Speicherplatz einplanen.

---

## Native App / PWA

Das Frontend ist als Progressive Web App konfiguriert und kann im Browser installiert werden. Zusätzlich ist Capacitor vorbereitet.

Native Wrapper bauen:

```bash
cd frontend
npm run build
npx cap add android   # einmalig, alternativ: ios
npx cap sync
npx cap open android
```

Für iOS wird eine macOS-Umgebung mit Xcode benötigt.

---

## Sicherheitshinweise

- Der Standardwert `changeme-in-production` für `JWT_SECRET` ist nur für lokale Entwicklung gedacht.
- Die Beispiel-Datenbankzugänge in `docker-compose.yml` sind nicht produktionsgeeignet.
- Live-Tracking verarbeitet Standortdaten. Für reale Einsätze sollten Zugriff, Aufbewahrung, Protokollierung und Löschung organisatorisch geregelt werden.
- Öffentliche Share-Links sind ohne Login abrufbar. Tokens sollten wie vertrauliche Links behandelt werden.
- Externe Dienste wie Open-Meteo, Overpass und Geofabrik können Verfügbarkeit, Limits oder Nutzungsbedingungen haben.

---

## Roadmap-Ideen

Diese Punkte sind mögliche nächste Ausbauschritte:

- Import vorhandener GPX-/GeoJSON-Routen.
- Rechte- und Rollenprüfung pro Organisation weiter verfeinern.
- Benachrichtigungen bei Verzögerungen oder Abweichungen von der Route.
- Audit-Log für Änderungen an Marschbefehlen und Konvois.
- Offline-First-Synchronisation für mobile Nutzung.
- CI-Pipeline für Backend-Tests, Frontend-Checks und Docker-Builds.
- Erweiterte Einsatzdokumentation und Einsatznachbereitung.

---

## Lizenz

Dieses Projekt steht unter der MIT-Lizenz.

---

<p align="center">
  <strong>MarschPlan</strong> – strukturierte Marschverbandsplanung für moderne Einsatzorganisationen.
</p>
