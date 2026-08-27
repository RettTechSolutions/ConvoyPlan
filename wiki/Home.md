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
| Auto-Updater | Drei Update-Kanäle (Stable/Beta/Nightly) im Admin-Bereich, automatische oder benachrichtigte Installation |
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
     └── Open-Meteo / Overpass / Autobahn-API / HERE·TomTom

Updater-Container   → git-poll auto-deploy
Retention-Container → periodischer Daten-Purge
```

- **Caddy** übernimmt TLS-Terminierung (Let's Encrypt oder eigenes Zertifikat), leitet `/api/*` und `/ws/*` ans Backend und alles andere ans Frontend und liefert Security-Header sowie eine Content-Security-Policy aus.
- **SvelteKit Frontend** stellt alle Nutzeroberflächen bereit: Login, Setup-Wizard, Planung, Tracking, Admin.
- **FastAPI Backend** bündelt Authentifizierung, Geschäftslogik, Routing, Exporte und externe Integrationen.
- **PostgreSQL + PostGIS** speichert alle Nutzer-, Fahrzeug-, Konvoi- und Geodaten.
- **GraphHopper** läuft selbst gehostet und berechnet Routen auf Basis von OpenStreetMap-Daten.
- **Updater-Container** pollt das Repository und deployt neue Commits automatisch; der **Retention-Container** löscht abgelaufene Live-Positionen, Audit-Log-Einträge und widerrufene Share-Links.

---

## Tech-Stack

| Schicht | Technologie |
|---|---|
| Frontend | SvelteKit, Svelte 5, TypeScript, Vite |
| Karte | MapLibre GL, OpenStreetMap |
| Backend | Python 3.12, FastAPI, Uvicorn |
| Datenbank | PostgreSQL 15, PostGIS |
| ORM / Migrationen | SQLAlchemy Async, Alembic |
| Authentifizierung | JWT (python-jose, passlib), MFA/TOTP |
| Routing | GraphHopper 9.1 |
| Externe Daten | Open-Meteo, Overpass, Autobahn-API, offene Feeds (MobiData BW, Berlin VIZ), DATEX-II/mobilithek, HERE/TomTom (optional) |
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
- Live-Tracking per WebSocket mit Fahrzeugstatus, Projektion auf die Route und Wegpunkt-/Kanalwechsel-Meldungen
- Wetter via Open-Meteo (kein API-Key erforderlich)
- Sperrungen und Baustellen aus mehreren Quellen: Overpass (DACH-weit), Autobahn-API (bund.dev), offene Feeds (MobiData BW, Berlin VIZ) und optional DATEX-II/mobilithek (weitere Bundesländer, auch mTLS-geschützt) – entlang der gesamten Route; fällt eine Quelle aus, liefern die anderen weiter. ASFINAG (AT) und opentransportdata.swiss (CH) lassen sich als DATEX-II-Feeds ergänzen
- Live-Verkehrslage (Stau) optional über HERE oder TomTom, sobald ein API-Key hinterlegt ist
- Leitstellen (global und org-eigen) und automatische Kanalwechselpunkte entlang der Route
- Export als PDF (Marschbefehl), GPX und JSON; Import von GPX/GeoJSON-Routen

### Betrieb, Sicherheit & Datenschutz
- Setup-Wizard für die Ersteinrichtung per Browser (kein SSH nötig)
- Admin-Bereich für Benutzer-, Leitstellen-, Branding- und Verkehrsdaten-Verwaltung
- Multi-Tenancy mit Org-Code-Slug und org-spezifischem Branding
- Auto-Updater (Kanäle Stable/Beta/Nightly, Modi automatisch/benachrichtigen)
- Lizenzmodell mit Demo-Modus; MFA/TOTP, SMTP-Dienst
- Security-Härtung, Audit-Log, DSGVO-Werkzeuge, Backup/Restore und Datenaufbewahrung
- CI-Pipeline für Tests, Typecheck und Docker-Build

---

## Wiki-Seiten

### Einrichtung & Referenz

| Seite | Inhalt |
|---|---|
| [Funktionsumfang](Funktionsumfang) | Vollständige Feature-Übersicht mit Status und Roadmap |
| [Installation und Setup](Installation-und-Setup) | Docker-Quickstart, Konfiguration, Deployment |
| [API-Dokumentation](API-Dokumentation) | Alle REST- und WebSocket-Endpunkte |
| [Benutzerhandbuch](Benutzerhandbuch) | Anleitung für Planer, Fahrer und Admins |
| [Entwicklung](Entwicklung) | Projektstruktur, lokaler Workflow, CI/Releases |

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

### Betrieb, Sicherheit & Features

| Seite | Inhalt |
|---|---|
| [Verkehrsdaten](Verkehrsdaten) | Baustellen/Sperrungen und Live-Verkehrslage einrichten (HERE/TomTom, mobilithek) |
| [Multi-Tenancy](Multi-Tenancy) | Organisationen, Org-Code-Slug, Datenisolation |
| [Auto-Updater](Auto-Updater) | Update-Kanäle, Update-Modi und manueller Trigger |
| [Lizenz und Demo-Modus](Lizenz-und-Demo-Modus) | Lizenzaktivierung, Demo-Modus, Instanz-UUID |
| [Sicherheit und Datenschutz](Sicherheit-und-Datenschutz) | Härtung, Audit-Log, DSGVO, Backup/Restore, Retention |

---

## Datenmodell (Kurzform)

```
User ── Vehicles, Convoys, UserOrganizations
Organization ── org_code (URL-Slug), UserOrganizations
Convoy ── parent_convoy_id, organization_id, ConvoyVehicles,
          Waypoints, Route, VehiclePositions
Leitstelle ── boundary (GeoJSON/KML-Zuständigkeitsgebiet)
```

Details siehe [API-Dokumentation](API-Dokumentation#datenmodell).

---

## Lizenz

ConvoyPlan steht unter der [GNU Affero General Public License v3.0 (AGPL-3.0)](https://github.com/RettTechSolutions/ConvoyPlan/blob/main/LICENSE).
