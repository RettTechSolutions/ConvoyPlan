# API-Dokumentation

Die vollständige OpenAPI-Dokumentation wird automatisch von FastAPI bereitgestellt:

- **Swagger UI:** `/docs`
- **ReDoc:** `/redoc`
- **OpenAPI JSON:** `/openapi.json`

Lokal (Dev) sind sie unter `http://localhost:8000/docs` erreichbar.

> **Produktion:** `/docs`, `/redoc` und `/openapi.json` sind standardmäßig **deaktiviert (404)**.
> Mit `DOCS_API_KEY=<geheim>` lassen sie sich per API-Key absichern (einmaliger Aufruf über
> `/docs?key=<geheim>`, danach via HttpOnly-Cookie bzw. Header `X-API-Key`); mit `ENABLE_DOCS=true`
> werden sie offen freigegeben (nur für Dev/intern).

Alle Endpunkte (außer `/api/setup`, `/api/auth/*` und öffentlichen Share-/Track-Routen) erfordern einen gültigen JWT-Token im Header:

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
| `POST` | `/api/auth/password` | Eigenes Passwort ändern (liefert frisches Token) | Ja |
| `POST` | `/api/auth/password-reset` | Passwort-Reset anstoßen | Nein |

### MFA / TOTP

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `POST` | `/api/auth/mfa/setup` | TOTP-Einrichtung starten (QR-Code generieren) |
| `POST` | `/api/auth/mfa/confirm` | TOTP-Einrichtung bestätigen und aktivieren |
| `POST` | `/api/auth/mfa/verify` | TOTP-Code bei Login verifizieren |
| `DELETE` | `/api/auth/mfa` | MFA deaktivieren |

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
| `GET/POST` | `/api/admin/users` | Benutzer auflisten oder anlegen (`password` optional — ohne Angabe wird eines generiert; optionale `org_id`/`org_role` legen die Org-Mitgliedschaft in derselben Transaktion mit an) |
| `PATCH/DELETE` | `/api/admin/users/{user_id}` | Benutzer aktivieren/deaktivieren, Rolle setzen, löschen |
| `GET/POST` | `/api/admin/organizations` | Organisationen auflisten oder anlegen |
| `POST/DELETE` | `/api/admin/users/{user_id}/orgs` | Benutzer einer Organisation zuweisen oder entfernen |
| `GET/POST/DELETE` | `/api/admin/organizations/{org_id}/api-keys` | Org-gebundene API-Schlüssel verwalten |
| `GET` | `/api/admin/branding` | Aktuelles (globales) Branding abrufen |
| `PUT` | `/api/admin/branding` | Globales Branding (Logo, Farben, App-Name) aktualisieren |
| `POST` | `/api/admin/trigger-update` | Auto-Update manuell anstoßen |
| `GET` | `/api/admin/update-status` / `/api/admin/update-log` | Deploy-Stand bzw. Live-Update-Log (SSE) |
| `GET/PUT` | `/api/admin/settings/update-channel` | Update-Kanal (Stable/Beta/Nightly) lesen/setzen |
| `GET/PUT` | `/api/admin/settings/update-mode` | Update-Modus (Automatisch/Benachrichtigen) lesen/setzen |
| `GET/PUT` | `/api/admin/settings/smtp` | SMTP-Konfiguration lesen/setzen |
| `GET/PUT` | `/api/admin/settings/traffic-keys` | HERE-/TomTom-API-Keys lesen (ohne Klartext) und setzen |

### Demo-Sitzungen

Jede Demo-Nutzung läuft als eigene, befristete Organisation (`is_demo=true`). Diese Endpunkte verwalten offene Sitzungen im Admin-Bereich.

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET/PUT` | `/api/admin/settings/demo` | Demo-Modus an/aus und Sitzungsdauer (Stunden) konfigurieren |
| `GET` | `/api/admin/demo-sessions` | Offene Demo-Sitzungen auflisten (Ablaufzeit, Konvoi-Anzahl, Herkunft) |
| `POST` | `/api/admin/demo-sessions/{org_id}/extend` | Ablaufzeit einer Demo-Sitzung verlängern |
| `DELETE` | `/api/admin/demo-sessions/{org_id}` | Demo-Sitzung sofort beenden (Konvois, Org und Demo-Nutzer löschen) |

> Die Herkunftsfelder (`created_ip`, `created_location`) werden beim Start der Sitzung aus der Client-IP ermittelt und per Hintergrund-Geolokation (ipapi.co) um Stadt/Region/Land ergänzt — siehe [Lizenz und Demo-Modus](Lizenz-und-Demo-Modus#offene-demo-sitzungen-verwalten-admin).

---

## Sicherheit und Datenschutz

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `POST` | `/api/admin/users/{user_id}/reset-password` | Passwort als Superadmin zurücksetzen |
| `POST` | `/api/admin/users/{user_id}/reset-mfa` | MFA eines Benutzers zurücksetzen |
| `GET` | `/api/admin/audit-log` | Security-Audit-Log (Filter nach Aktion) |
| `GET` | `/api/admin/users/{user_id}/export` | Personenbezogene Daten exportieren (DSGVO Art. 15) |
| `DELETE` | `/api/admin/users/{user_id}/data` | Benutzerdaten löschen, Audit-Trail pseudonymisieren (Art. 17) |

---

## Lizenz

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/license/instance-id` | Instanz-UUID abfragen (für Lizenzbeantragung) |
| `GET` | `/api/license/status` | Lizenzstatus, `demo_mode` und `key_source` |
| `POST` | `/api/license/activate` | Lizenzschlüssel validieren, speichern und Cache zurücksetzen |

> Im Demo-Modus (kein gültiger Lizenzschlüssel) sind alle schreibenden Operationen (POST/PUT/PATCH/DELETE) mit **HTTP 402** gesperrt.

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

> Die Fahrzeit je Wegpunkt wird streckenproportional zur Gesamtroute berechnet; die Antwort enthält zusätzlich `planned_departure` (Abmarsch) und `planned_arrival` des Ziels — siehe [Konvoi-Planung → Automatische Zeitplanung](Konvoi-Planung#automatische-zeitplanung).

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

## Freigabelinks und Tracking-App

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET/POST/DELETE` | `/api/convoys/{convoy_id}/share-links` | Widerrufbare Freigabelinks pro Konvoi |
| `GET/POST` | `/api/track/{slug}` | Öffentliche Tracking-App: Status abrufen / Position senden |
| `WS` | `/api/ws/track/{slug}` | WebSocket der Tracking-App |

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

Position senden:

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

## Organisationen

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/organizations/` | Eigene Organisationen auflisten |
| `POST` | `/api/organizations/` | Neue Organisation anlegen |
| `DELETE` | `/api/organizations/{org_id}` | Organisation löschen |
| `POST` | `/api/organizations/{org_id}/members` | Bestehenden Benutzer per E-Mail zur Org hinzufügen (Org-Admin-Rolle erforderlich) — löst eine Benachrichtigungs-Mail mit Org-Login-Link an den neuen Mitglied aus |

> Siehe auch **[Multi-Tenancy](Multi-Tenancy)**.

### Org-Branding

Org-Admin-Rolle erforderlich (außer dem öffentlichen Slug-Endpunkt). Die Overrides gelten nur innerhalb `/o/[slug]`; das globale `/api/branding` (Superadmin, siehe oben) bleibt davon unberührt.

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/org/branding` | Effektives Branding der eigenen Org abrufen (Plattform-Branding + Org-Overrides zusammengeführt) |
| `PUT` | `/api/org/branding` | Branding-Overrides (Farben, App-Name) der eigenen Org setzen |
| `POST` | `/api/org/branding/logo/{slot}` | Logo hochladen (`slot`: `main` oder `horizontal`), PNG/JPG/SVG, max. 2 MB |
| `DELETE` | `/api/org/branding` | Alle Overrides entfernen — Org fällt zurück auf das Plattform-Branding |
| `GET` | `/api/branding/org/{slug}` | **Öffentlich:** effektives Branding einer Org per Slug (für die Org-Login-Seite, kein Login nötig) |

---

## Leitstellen

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET/POST/PUT/DELETE` | `/api/leitstellen/` | Globale (superadmin-gepflegte) Leitstellen verwalten |
| `GET/POST/PUT/DELETE` | `/api/org/leitstellen/` | Org-eigene Leitstellen verwalten |
| `POST` | `/api/org/leitstellen/{id}/submit` | Org-Leitstelle als globalen Vorschlag einreichen |
| `GET` | `/api/org/leitstellen/geojson` | Sichtbare Leitstellengebiete als GeoJSON (Übersichtskarte) |

---

## Wetter, Sperrungen und Verkehrslage

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/weather/?lat=48.13&lon=11.57` | Wetterdaten (Open-Meteo) |
| `GET` | `/api/overpass/closures?lat=..&lon=..` | Sperrungen/Baustellen im Radius um einen Punkt (Overpass, Autobahn-API, offene Feeds, DATEX-II) |
| `POST` | `/api/overpass/closures/route` | Sperrungen/Baustellen im Korridor entlang einer Routen-Geometrie |
| `GET` | `/api/traffic/flow/status` | Konfigurierten Verkehrslage-Anbieter (HERE/TomTom) abfragen |
| `GET` | `/api/traffic/flow` | Live-Verkehrslage im Radius um einen Punkt |
| `POST` | `/api/traffic/flow/route` | Live-Verkehrslage entlang einer Routen-Geometrie |

> Einrichtung der optionalen Quellen: **[Verkehrsdaten](Verkehrsdaten)**.

---

## System

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/version` | Build-Version, Commit-SHA und Update-Hinweis |
| `GET` | `/api/version/changelog` | Release-Notes der laufenden Version (gecacht) |
| `GET` | `/health` | Health-Check mit Versionsangabe |

---

## Systemübersicht (Superadmin)

Hardware-, Container- und Nutzungskennzahlen der Instanz — dieselbe Datenbasis,
die der Reiter **Systemübersicht** im Admin-Portal anzeigt. Alle Endpunkte
erfordern einen Superadmin-Token. Details siehe
[Systemübersicht](Systemuebersicht).

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/admin/system/overview` | Live-Zustand: CPU, RAM, Platten, PSI-Druck, Container, Datenbank, aktive Benutzer |
| `GET` | `/api/admin/system/containers` | Container-Zustände inkl. Healthcheck und CPU/RAM je Container |
| `GET` | `/api/admin/system/history` | Verlauf (`range=1h…365d` oder `from`/`to`, `resolution=auto\|raw\|hour\|day`, `format=json\|csv`) |
| `GET` | `/api/admin/system/usage` | Portalnutzung je Tag (`days=1…1095`) |
| `GET` | `/api/admin/system/reports/months` | Monate mit verfügbarem Bericht |
| `GET` | `/api/admin/system/reports/monthly` | Monatsbericht (`month=JJJJ-MM`, `format=json\|csv\|pdf`) |
| `POST` | `/api/admin/system/sample` | Stichprobe sofort erfassen |

Beispiel — Monatsbericht als PDF holen:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://web.convoyplan.de/api/admin/system/reports/monthly?month=2026-07&format=pdf" \
  -o systembericht-2026-07.pdf
```

Beispiel — Auslastung der letzten 30 Tage für ein Monitoring-System:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://web.convoyplan.de/api/admin/system/history?range=30d&resolution=hour"
```

---

## Datenmodell

```
User
├── Vehicles
├── Convoys
└── UserOrganizations

Organization
├── org_code                # Kurzer URL-Slug (4–8 Zeichen), eindeutig
├── branding                # JSON-Override, überlagert das globale Plattform-Branding
└── UserOrganizations

Convoy
├── parent_convoy_id        # Teilverband / Sub-Convoy
├── organization_id         # Mandant / Organisation
├── ConvoyVehicles          # Fahrzeugzuordnung inkl. Status
├── Waypoints               # Wegpunkte, Kontrollpunkte, Halte
├── Route                   # Geometrie, Distanz, Dauer, GPX, Kanalwechsel
└── VehiclePositions        # Live-Tracking-Positionen

Leitstelle
└── boundary                # GeoJSON/KML-Zuständigkeitsgebiet
```
