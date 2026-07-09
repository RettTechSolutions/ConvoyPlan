# API-Dokumentation

Die vollständige OpenAPI-Dokumentation wird automatisch von FastAPI bereitgestellt:

- **Swagger UI:** `https://<DOMAIN>/api/docs`
- **OpenAPI JSON:** `https://<DOMAIN>/api/openapi.json`

Alle Endpunkte (außer `/api/setup` und `/api/auth`) erfordern einen gültigen JWT-Token im Header:

```
Authorization: Bearer <token>
```

---

## Authentifizierung

### Token erhalten

```http
POST /api/auth/login
Content-Type: application/json

{
  "email": "benutzer@example.com",
  "password": "passwort"
}
```

Antwort:

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

### Endpunkte

| Methode | Endpunkt | Beschreibung | Auth |
|---|---|---|---|
| `POST` | `/api/auth/register` | Account erstellen | Nein |
| `POST` | `/api/auth/login` | Login, JWT erhalten | Nein |

---

## Ersteinrichtung (Setup-Wizard)

| Methode | Endpunkt | Beschreibung | Auth |
|---|---|---|---|
| `GET` | `/api/setup/status` | Prüft ob Setup noch erforderlich ist | Nein |
| `POST` | `/api/setup` | Superadmin anlegen, Domain und TLS konfigurieren | Nein |

---

## Superadmin-Verwaltung

Nur für Benutzer mit Superadmin-Rolle zugänglich.

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/admin/users` | Alle Benutzer auflisten |
| `PATCH` | `/api/admin/users/{user_id}` | Benutzer aktivieren/deaktivieren, Rolle setzen |
| `GET` | `/api/admin/branding` | Aktuelles Branding abrufen |
| `PUT` | `/api/admin/branding` | Branding (Logo, Farben, App-Name) aktualisieren |
| `POST` | `/api/admin/trigger-update` | Manuelles Update auslösen |

---

## Fahrzeuge

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/vehicles/` | Alle Fahrzeuge auflisten |
| `POST` | `/api/vehicles/` | Neues Fahrzeug anlegen |
| `GET` | `/api/vehicles/{vehicle_id}` | Fahrzeug abrufen |
| `PUT` | `/api/vehicles/{vehicle_id}` | Fahrzeug aktualisieren |
| `DELETE` | `/api/vehicles/{vehicle_id}` | Fahrzeug löschen |

**Fahrzeug-Felder:**

| Feld | Typ | Beschreibung |
|---|---|---|
| `callsign` | string | Funkrufname |
| `plate` | string | Kennzeichen |
| `length_m` | float | Fahrzeuglänge in Metern |
| `width_m` | float | Fahrzeugbreite in Metern |
| `weight_kg` | float | Gewicht in Kilogramm |
| `fuel_type` | string | Kraftstoffart |
| `fuel_capacity_l` | float | Tankvolumen in Litern |
| `fuel_consumption_per_100km` | float | Verbrauch auf 100 km |

---

## Marschverbände (Convoys)

### Grundlegende Verwaltung

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/convoys/` | Alle Marschverbände auflisten |
| `POST` | `/api/convoys/` | Neuen Marschverband anlegen |
| `GET` | `/api/convoys/{convoy_id}` | Marschverband abrufen |
| `PUT` | `/api/convoys/{convoy_id}` | Marschverband bearbeiten |
| `DELETE` | `/api/convoys/{convoy_id}` | Marschverband löschen |

### Fahrzeuge zuordnen

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `POST` | `/api/convoys/{convoy_id}/vehicles` | Fahrzeug dem Konvoi zuordnen |
| `DELETE` | `/api/convoys/{convoy_id}/vehicles/{vehicle_id}` | Fahrzeug aus Konvoi entfernen |

### Wegpunkte

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/convoys/{convoy_id}/waypoints` | Wegpunkte abrufen |
| `POST` | `/api/convoys/{convoy_id}/waypoints` | Wegpunkt hinzufügen |
| `PUT` | `/api/convoys/{convoy_id}/waypoints/{waypoint_id}` | Wegpunkt aktualisieren |
| `DELETE` | `/api/convoys/{convoy_id}/waypoints/{waypoint_id}` | Wegpunkt entfernen |

**Wegpunkt-Typen:** `start`, `stop`, `checkpoint`, `fuel_stop`, `technical_halt`

### Routing

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `POST` | `/api/convoys/{convoy_id}/calculate-route` | Route und Zeitplan berechnen |

### Teilverbände

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/convoys/{convoy_id}/sub-convoys` | Teilverbände abrufen |
| `POST` | `/api/convoys/{convoy_id}/sub-convoys` | Neuen Teilverband erstellen |

### Export und Import

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/convoys/{convoy_id}/export/gpx` | Route als GPX exportieren |
| `GET` | `/api/convoys/{convoy_id}/export/json` | Route als JSON exportieren |
| `GET` | `/api/convoys/{convoy_id}/export/pdf` | Marschbefehl als PDF exportieren |
| `POST` | `/api/convoys/{convoy_id}/import/gpx` | GPX-Track importieren |
| `POST` | `/api/convoys/{convoy_id}/import/geojson` | GeoJSON-Route importieren |

### Zusatzfunktionen

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/convoys/{convoy_id}/fuel-stations` | Tankstellen entlang der Route |
| `GET` | `/api/convoys/share/{token}` | Öffentliche Routenansicht (kein Login) |

---

## Live-Tracking

### REST

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/convoys/{convoy_id}/positions` | Aktuelle Positionen aller Fahrzeuge |
| `POST` | `/api/convoys/{convoy_id}/positions` | Eigene Position aktualisieren |
| `PATCH` | `/api/convoys/{convoy_id}/vehicles/{vehicle_id}/status` | Fahrzeugstatus setzen |

**Fahrzeugstatus-Werte:** `planned`, `en_route`, `arrived`, `delayed`

### WebSocket

```
WS /ws/tracking/{convoy_id}?token=<jwt>
```

Verbindung herstellen und Positionsupdates empfangen/senden:

```json
{
  "type": "position_update",
  "vehicle_id": 42,
  "lat": 48.1374,
  "lon": 11.5755
}
```

Eingehende Updates vom Server:

```json
{
  "type": "positions",
  "data": [
    {
      "vehicle_id": 42,
      "callsign": "RTW 1-1",
      "lat": 48.1374,
      "lon": 11.5755,
      "status": "en_route",
      "timestamp": "2026-05-18T14:30:00Z"
    }
  ]
}
```

---

## Lagedaten

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/convoys/{convoy_id}/lage` | Alle Lagedaten-Layer abrufen |
| `POST` | `/api/convoys/{convoy_id}/lage` | GeoJSON-Layer hochladen |
| `PUT` | `/api/convoys/{convoy_id}/lage/{layer_id}` | Layer aktualisieren |
| `DELETE` | `/api/convoys/{convoy_id}/lage/{layer_id}` | Layer löschen |

---

## Wetter und Sperrungen

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/weather/?lat=48.13&lon=11.57` | Wetterdaten für Koordinaten (Open-Meteo) |
| `GET` | `/api/overpass/closures?lat=48.13&lon=11.57` | Sperrungen und Baustellen (OSM Overpass) |

---

## Organisationen

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/organizations/` | Eigene Organisationen auflisten |
| `POST` | `/api/organizations/` | Neue Organisation anlegen |
| `DELETE` | `/api/organizations/{org_id}` | Organisation löschen |
| `POST` | `/api/organizations/{org_id}/invite` | Mitglied einladen |
| `DELETE` | `/api/organizations/{org_id}/members/{user_id}` | Mitglied entfernen |

---

## Leitstellen

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/leitstellen/` | Alle Leitstellen auflisten |
| `POST` | `/api/leitstellen/` | Neue Leitstelle anlegen |
| `PUT` | `/api/leitstellen/{id}` | Leitstelle aktualisieren |
| `DELETE` | `/api/leitstellen/{id}` | Leitstelle löschen |

---

## System

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/status` | Systemstatus abrufen |
| `GET` | `/health` | Health-Check |

---

## Datenmodell

```
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
├── Waypoints               # Wegpunkte, Kontrollpunkte, Halte
├── Route                   # Geometrie, Distanz, Dauer, GPX, Kanalwechsel
├── VehiclePositions        # Live-Tracking-Positionen
└── LageLayers              # GeoJSON-Lagedaten

Leitstelle
└── boundary                # GeoJSON/KML-Zuständigkeitsgebiet
```
