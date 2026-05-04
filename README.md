# MarschPlan

**Browserbasierte Planungssoftware für Marschverbände – entwickelt für BOS-Organisationen.**

MarschPlan ermöglicht die strukturierte Planung von Konvois: Fahrzeuge verwalten, Routen auf der Karte festlegen, Zeitpläne automatisch berechnen und die Route als GPX exportieren oder per Link teilen.

---

## Features (MVP)

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
| PWA | vite-plugin-pwa |
| Infrastruktur | Docker Compose |

---

## Projektstruktur

```
marschplan/
├── frontend/          # SvelteKit App
│   └── src/
│       ├── lib/
│       │   ├── components/   # MapView, UI-Komponenten
│       │   ├── stores/       # auth, convoy, map
│       │   └── api/          # API-Client
│       └── routes/
│           ├── login/
│           ├── plan/         # Planungsmodus
│           └── share/[token] # Öffentliche Routenansicht
├── backend/           # FastAPI
│   ├── app/
│   │   ├── api/routes/   # auth, vehicles, convoys, routing
│   │   ├── models/        # SQLAlchemy ORM
│   │   ├── schemas/       # Pydantic
│   │   └── services/      # routing, schedule, export, geometry
│   └── alembic/           # DB-Migrationen
├── graphhopper/       # GraphHopper Konfiguration
└── docker-compose.yml
```

---

## Quickstart

### Voraussetzungen

- Docker + Docker Compose
- Node.js 20+
- Python 3.12+ (nur für lokale Backend-Entwicklung ohne Docker)

### 1. Repo klonen

```bash
git clone https://github.com/RettTechSolutions/MarschPlan.git
cd MarschPlan
```

### 2. OSM-Daten herunterladen

GraphHopper benötigt eine OSM-Datei. Für Deutschland:

```bash
cd graphhopper
wget https://download.geofabrik.de/europe/germany-latest.osm.pbf
cd ..
```

> Für kleinere Testregionen z. B. `berlin-latest.osm.pbf` von Geofabrik verwenden.

### 3. Backend & Datenbank starten

```bash
docker-compose up -d db backend graphhopper
```

Beim ersten Start werden automatisch die Datenbankmigrationen ausgeführt (PostGIS-Extension + alle Tabellen).

### 4. Frontend starten

```bash
cd frontend
npm install
npm run dev
```

App läuft unter **http://localhost:5173**

### 5. Account erstellen

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
| POST | `/api/auth/login` | Login → JWT-Token |
| GET/POST/PUT/DELETE | `/api/vehicles/` | Fahrzeugverwaltung |
| GET/POST/PUT/DELETE | `/api/convoys/` | Marschverbandsverwaltung |
| POST/PUT/DELETE | `/api/convoys/{id}/waypoints` | Wegpunkte |
| POST | `/api/convoys/{id}/vehicles` | Fahrzeug zuweisen |
| POST | `/api/convoys/{id}/calculate-route` | Route + Zeitplan berechnen |
| GET | `/api/convoys/{id}/export/gpx` | GPX-Export |
| GET | `/api/convoys/{id}/export/json` | JSON-Export |
| GET | `/api/convoys/share/{token}` | Öffentliche Ansicht (kein Login) |

Vollständige Swagger-Doku: **http://localhost:8000/docs**

---

## Datenmodell

```
Benutzer
└── Marschverband (Convoy)
    ├── Fahrzeuge (via convoy_vehicles)
    ├── Wegpunkte (geordnet, mit Haltezeit + Zeitplan)
    └── Route (Geometrie, Distanz, Fahrzeit, GPX)

Fahrzeug
├── Name, Funkrufname, Kennzeichen
└── Höhe, Gewicht, Länge, Funktion im Konvoi
```

### Routingparameter (pro Marschverband)

- Geschwindigkeit innerorts / außerorts
- Maximale Fahrzeughöhe (aus Fahrzeugdaten ermittelt)
- Maximales Fahrzeuggewicht
- Wegpunkte in definierter Reihenfolge

---

## Ausbaustufen

### Version 2

- Benutzer- und Rollenmodell (Planer, Fahrer, Beobachter)
- Mehrere Organisationen / Mandanten
- Teilverbände
- Technische Halte
- PDF-Export Marschbefehl
- Offline-Karten

### Version 3

- Live-Tracking (GPS-Position der Fahrzeuge)
- Teilnehmerstatus
- Wetterintegration
- Sperrungen / Baustellen
- Lagedatenintegration
- Native App-Wrapper (Android / iOS)

---

## Entwicklung

### Backend lokal (ohne Docker)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Datenbankverbindung in .env konfigurieren
alembic upgrade head
uvicorn app.main:app --reload
```

### Umgebungsvariablen Backend

| Variable | Standard | Beschreibung |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL-Verbindung |
| `JWT_SECRET` | `changeme-in-production` | JWT-Signing-Key |
| `GRAPHHOPPER_URL` | `http://localhost:8989` | GraphHopper-Endpunkt |

### Umgebungsvariablen Frontend

| Variable | Standard | Beschreibung |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000` | Backend-URL |

---

## Lizenz

MIT
