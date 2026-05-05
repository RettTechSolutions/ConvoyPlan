# MarschPlan

**Browserbasierte Planungssoftware für Marschverbände – entwickelt für BOS-Organisationen.**

MarschPlan ermöglicht die strukturierte Planung von Konvois: Fahrzeuge verwalten, Routen auf der Karte festlegen, Zeitpläne automatisch berechnen, Live-Tracking, Wetter- und Sperrungsintegration.

---

## Features

### V1 – MVP (implementiert)

| Funktion | Status |
|---|---|
| Web-Login (JWT) | ✅ |
| Karte mit OpenStreetMap | ✅ |
| Start / Ziel / Wegpunkte setzen | ✅ |
| Fahrzeuge anlegen (Höhe, Gewicht, Funkrufname …) | ✅ |
| Marschverband zusammenstellen | ✅ |
| Geschwindigkeit innerorts / außerorts konfigurieren | ✅ |
| Routenberechnung via GraphHopper | ✅ |
| Zeitplan automatisch berechnen | ✅ |
| GPX-Export | ✅ |
| JSON-Export | ✅ |
| Route per Link teilen (ohne Login) | ✅ |
| Progressive Web App (installierbar) | ✅ |

### V2 – Erweitert (implementiert)

| Funktion | Status |
|---|---|
| Benutzer- und Rollenmodell (Admin / Planer / Fahrer / Beobachter) | ✅ |
| Mehrere Organisationen / Mandanten | ✅ |
| Teilverbände (Sub-Convoys mit Eltern-Konvoi) | ✅ |
| Technische Halte (Tanken, Pause, Wartung) | ✅ |
| PDF-Export Marschbefehl | ✅ |
| Offline-Karten (PWA-Tile-Caching) | ✅ |

### V3 – Live & Integrationen (implementiert)

| Funktion | Status |
|---|---|
| Live-Tracking via WebSocket | ✅ |
| GPS-Position automatisch senden (Browser Geolocation) | ✅ |
| Fahrzeugstatus (Geplant / Unterwegs / Angekommen / Verspätung) | ✅ |
| Wetterintegration (open-meteo.com, kostenlos) | ✅ |
| Sperrungen & Baustellen (OpenStreetMap Overpass-API) | ✅ |
| Lagedaten (GeoJSON-Layer hochladen / anzeigen) | ✅ |
| Native App-Wrapper (Capacitor-Konfiguration) | ✅ |

---

## Tech-Stack

| Schicht | Technologie |
|---|---|
| Frontend | SvelteKit + TypeScript |
| Karte | MapLibre GL + OpenStreetMap |
| Backend | Python FastAPI |
| Datenbank | PostgreSQL + PostGIS |
| Routing | GraphHopper (self-hosted, Docker) |
| Auth | JWT (python-jose + passlib) |
| ORM / Migrationen | SQLAlchemy (async) + Alembic |
| Live-Tracking | WebSocket (FastAPI native) |
| Wetter | open-meteo.com (kein API-Key nötig) |
| Sperrungen | OpenStreetMap Overpass API |
| PDF | fpdf2 |
| PWA | vite-plugin-pwa |
| Native App | Capacitor (iOS / Android) |
| Infrastruktur | Docker Compose |

---

## Projektstruktur

```
marschplan/
├── frontend/
│   ├── src/
│   │   ├── lib/
│   │   │   ├── api/          # API-Client (client.ts, index.ts)
│   │   │   ├── components/   # MapView, WeatherWidget, LageLayerPanel
│   │   │   └── stores/       # auth, convoy, map, tracking, lage
│   │   └── routes/
│   │       ├── login/
│   │       ├── plan/         # Planungsmodus (alle Features)
│   │       ├── tracking/     # Live-Tracking-Ansicht
│   │       └── share/[token] # Öffentliche Routenansicht
│   └── capacitor.config.ts   # Native App (iOS/Android)
├── backend/
│   ├── app/
│   │   ├── api/routes/       # auth, vehicles, convoys, routing,
│   │   │                     # organizations, tracking, lage, weather, overpass
│   │   ├── models/           # User, Vehicle, Convoy, Waypoint, Route,
│   │   │                     # Organization, VehiclePosition, LageLayer
│   │   ├── schemas/          # Pydantic-Schemas
│   │   └── services/         # routing, schedule, export, pdf,
│   │                         # weather, overpass, tracking (WS-Manager)
│   └── alembic/versions/     # 0001 Initial, 0002 V2+V3
├── graphhopper/config.yml
└── docker-compose.yml
```

---

## Quickstart

### 1. Repo klonen

```bash
git clone https://github.com/RettTechSolutions/MarschPlan.git
cd MarschPlan
```

### 2. Stack starten

```bash
docker-compose up -d
```

**Beim ersten Start lädt GraphHopper die OSM-Kartendaten automatisch herunter** (~4 GB für Deutschland).
Datenbank-Migrationen laufen ebenfalls automatisch. Das Backend wartet per Healthcheck auf GraphHopper.

Fortschritt verfolgen:
```bash
docker-compose logs -f graphhopper
```

> **Schnellstart für Tests** – nur Berlin (~30 MB) in `docker-compose.yml` setzen:
> ```yaml
> OSM_DOWNLOAD_URL: https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
> OSM_FILENAME: berlin-latest.osm.pbf
> ```
> Weitere Regionen: [download.geofabrik.de](https://download.geofabrik.de)

### 3. Frontend starten

```bash
cd frontend
npm install
npm run dev
```

App läuft unter **http://localhost:5173**

### 4. Ersten Account anlegen

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "pilot@bos.de", "password": "sicher123"}'
```

---

## API-Übersicht

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| POST | `/api/auth/register` | Account erstellen |
| POST | `/api/auth/login` | Login → JWT |
| CRUD | `/api/vehicles/` | Fahrzeuge |
| CRUD | `/api/convoys/` | Marschverbände |
| POST | `/api/convoys/{id}/sub-convoys` | Teilverband erstellen |
| CRUD | `/api/convoys/{id}/waypoints` | Wegpunkte |
| POST | `/api/convoys/{id}/calculate-route` | Route + Zeitplan |
| GET | `/api/convoys/{id}/export/gpx` | GPX-Export |
| GET | `/api/convoys/{id}/export/json` | JSON-Export |
| GET | `/api/convoys/{id}/export/pdf` | Marschbefehl PDF |
| GET | `/api/convoys/share/{token}` | Öffentliche Ansicht |
| CRUD | `/api/organizations/` | Organisationen |
| GET/POST | `/api/convoys/{id}/positions` | Live-Positionen |
| PATCH | `/api/convoys/{id}/vehicles/{vid}/status` | Fahrzeugstatus |
| WS | `/api/ws/tracking/{convoy_id}?token=…` | WebSocket Tracking |
| CRUD | `/api/convoys/{id}/lage` | GeoJSON-Lagedaten |
| GET | `/api/weather/?lat=…&lon=…` | Wetter (open-meteo) |
| GET | `/api/overpass/closures?lat=…&lon=…` | Sperrungen (OSM) |

Vollständige Swagger-Doku: **http://localhost:8000/docs**

---

## Datenmodell

```
Benutzer ─── UserOrganization ─── Organisation
    │
    └── Marschverband (Convoy)
            ├── parent_convoy_id → Teilverband
            ├── organization_id  → Organisation
            ├── Fahrzeuge (convoy_vehicles + vehicle_status)
            ├── Wegpunkte (type + halt_purpose + Zeitplan)
            ├── Route (Geometrie, GPX)
            ├── VehiclePositions (Live-Tracking)
            └── LageLayers (GeoJSON-Daten)
```

---

## Native App (V3)

Capacitor ist vorkonfiguriert. Zum Bauen:

```bash
cd frontend
npm run build
npx cap add android   # oder ios
npx cap sync
npx cap open android  # öffnet Android Studio
```

---

## Umgebungsvariablen

### Backend

| Variable | Standard | Beschreibung |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://…` | PostgreSQL-Verbindung |
| `JWT_SECRET` | `changeme-in-production` | **Unbedingt ändern!** |
| `GRAPHHOPPER_URL` | `http://localhost:8989` | Routing-Engine |

### GraphHopper

| Variable | Standard | Beschreibung |
|---|---|---|
| `OSM_DOWNLOAD_URL` | `…/germany-latest.osm.pbf` | Geofabrik-URL der OSM-Region |
| `OSM_FILENAME` | `germany-latest.osm.pbf` | Dateiname im Volume |
| `JAVA_OPTS` | `-Xmx2g -Xms512m` | JVM-Heap (mind. 1 g für kleine Regionen) |

### Frontend

| Variable | Standard | Beschreibung |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000` | Backend-URL |

---

## Lizenz

MIT
