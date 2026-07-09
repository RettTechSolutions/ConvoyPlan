# ConvoyPlan – Projektübersicht

**Browserbasierte Planungssoftware für Marschverbände, Konvois und Einsatzfahrten von BOS-Organisationen.**

Kartenbasierte Routenplanung · Live-Tracking · Marschbefehl-PDF · Self-hosted · Docker

---

## Was ist ConvoyPlan?

ConvoyPlan ist eine selbst gehostete Web-Anwendung, die Einsatzorganisationen (BOS) bei der strukturierten Planung und Durchführung von Marschverbänden und Konvoifahrten unterstützt. Die Software läuft vollständig on-premise und erfordert keine Cloud-Dienste.

---

## Highlights

| Feature | Beschreibung |
|---|---|
| Kartenbasierte Planung | Interaktive OSM-Karte mit MapLibre GL |
| Routing | Selbst gehostete GraphHopper-Engine |
| Live-Tracking | Positionsupdates per WebSocket und Browser-Geolocation |
| Marschbefehl-PDF | Automatische PDF-Generierung aus der Planung |
| Export | GPX, JSON, PDF für Navigation und Dokumentation |
| Rollen & Mandanten | Admin, Planer, Fahrer, Beobachter je Organisation |
| Branding | Eigenes Logo, Farben und App-Name konfigurierbar |
| PWA / Native App | Installierbar im Browser, Capacitor für Android/iOS |
| Auto-Updater | Git-Polling-Container deployt neue Commits automatisch |
| Self-hosted | Vollständig on-premise, kein Cloud-Zwang |

---

## Architektur

```
Browser / PWA / Capacitor App
        │ HTTPS / WSS
        ▼
Caddy Reverse Proxy (TLS + WebSocket)
     │               │
     ▼               ▼
FastAPI Backend   SvelteKit Frontend
     │
     ├── PostgreSQL + PostGIS
     ├── GraphHopper (Routing)
     └── Open-Meteo / Overpass API
```

- **Caddy** übernimmt TLS-Terminierung (Let's Encrypt oder eigenes Zertifikat) und leitet Anfragen ans Backend und Frontend weiter.
- **SvelteKit Frontend** stellt alle Nutzeroberflächen bereit: Login, Setup-Wizard, Planung, Tracking, Admin.
- **FastAPI Backend** bündelt Authentifizierung, Geschäftslogik, Routing, Exporte und externe Integrationen.
- **PostgreSQL + PostGIS** speichert alle Nutzer-, Fahrzeug-, Konvoi- und Geodaten.
- **GraphHopper** läuft selbst gehostet und berechnet Routen auf Basis von OpenStreetMap-Daten.

---

## Tech-Stack

| Schicht | Technologie |
|---|---|
| Frontend | SvelteKit, Svelte 5, TypeScript, Vite |
| Karte | MapLibre GL, OpenStreetMap |
| Backend | Python 3.12, FastAPI, Uvicorn |
| Datenbank | PostgreSQL 15, PostGIS |
| ORM / Migrationen | SQLAlchemy Async, Alembic |
| Authentifizierung | JWT (python-jose, passlib) |
| Routing | GraphHopper 9.1 |
| Reverse Proxy / TLS | Caddy 2 |
| Infrastruktur | Docker Compose, Portainer Stack |

---

## Funktionsumfang

### Planung und Routing
- Interaktive OSM-Karte mit Wegpunkten, Kontrollpunkten und technischen Halten
- Automatische Zeitplanung anhand von Startzeit und Marschgeschwindigkeiten
- Separate innerörtliche und außerörtliche Marschgeschwindigkeit
- Kraftstoffplanung mit Tankstellenabfrage entlang der Route
- Import vorhandener GPX- und GeoJSON-Routen

### Verwaltung und Zusammenarbeit
- Organisations- und Rollenmodell (Admin, Planer, Fahrer, Beobachter)
- Fahrzeugverwaltung mit Funkrufname, Kennzeichen, Abmessungen und Kraftstoffdaten
- Teilverbände (Sub-Convoys) mit Parent-Konvoi-Zuordnung
- Freigabelink für öffentliche Routenansicht ohne Login

### Live, Lage und Export
- Live-Tracking per WebSocket mit Fahrzeugstatus
- GeoJSON-Lagedaten hochladen und auf der Karte anzeigen
- Wetter via Open-Meteo (kein API-Key erforderlich)
- Sperrungen und Baustellen via OpenStreetMap Overpass API
- Leitstellen und automatische Kanalwechselpunkte entlang der Route
- Export als PDF (Marschbefehl), GPX und JSON

### Betrieb
- Setup-Wizard für die Ersteinrichtung per Browser (kein SSH nötig)
- Admin-Bereich für Benutzer-, Leitstellen- und Branding-Verwaltung
- Auto-Updater deployt neue Commits automatisch
- CI-Pipeline für Tests, Typecheck und Docker-Build

---

## Wiki-Seiten

### Einrichtung & Referenz

| Seite | Inhalt |
|---|---|
| [Installation und Setup](Installation-und-Setup) | Docker-Quickstart, Konfiguration, Deployment |
| [API-Dokumentation](API-Dokumentation) | Alle REST- und WebSocket-Endpunkte |
| [Benutzerhandbuch](Benutzerhandbuch) | Anleitung für Planer, Fahrer und Admins |

### Bedienung (Schritt für Schritt)

| Seite | Inhalt |
|---|---|
| [Erste Schritte](Erste-Schritte) | Registrierung, Login und erster Überblick |
| [Konvoi-Planung](Konvoi-Planung) | Konvois anlegen, Wegpunkte und Route berechnen |
| [Fahrzeuge](Fahrzeuge) | Fahrzeuge anlegen und verwalten |
| [Live-Tracking](Live-Tracking) | Echtzeit-Verfolgung der Fahrzeuge |
| [Marschbefehl & Export](Marschbefehl-Export) | PDF-Marschbefehl sowie GPX-/JSON-Export |
| [Rollen & Berechtigungen](Rollen) | Rollenmodell und Zugriffsrechte |
| [Teilen](Teilen) | Öffentliche Freigabelinks ohne Login |
| [FAQ](FAQ) | Häufige Fragen |

---

## Lizenz

ConvoyPlan steht unter der [GNU Affero General Public License v3.0 (AGPL-3.0)](https://github.com/RettTechSolutions/ConvoyPlan/blob/main/LICENSE).
