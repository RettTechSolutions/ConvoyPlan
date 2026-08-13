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

---

## Zugangswege im Überblick

ConvoyPlan kennt **vier voneinander unabhängige Credentials**. Welches du brauchst,
hängt vom Endpunkt ab — die Tabelle nennt jeweils den kürzesten Weg.

| Zugangsweg | Wie mitgeben | Gilt für | Woher |
|---|---|---|---|
| **Bearer-Token (JWT)** | `Authorization: Bearer <token>` | alle geschützten Endpunkte | `POST /api/auth/login` |
| **Org-API-Key** | `X-API-Key: cvp_…` | organisationsbezogene Endpunkte (siehe [Matrix](#welche-endpunkte-akzeptieren-einen-org-api-key)) | Superadmin-Portal → Reiter **API-Keys** |
| **System-API-Key** | `X-API-Key: cvp_…` | nur lesende Endpunkte der [Systemübersicht](#systemübersicht-superadmin) | Superadmin-Portal → **API-Keys** → Geltungsbereich *System* |
| **Freigabe-Token** | Teil der URL | `/api/convoys/share/{token}`, `/api/track/{slug}` | Freigabelink je Konvoi |
| **Docs-Key** | `X-API-Key: <DOCS_API_KEY>` oder `?key=…` | nur `/docs`, `/redoc`, `/openapi.json` | Umgebungsvariable `DOCS_API_KEY` |

> ⚠️ **Docs-Key ≠ Org-API-Key.** Beide reisen im Header `X-API-Key`, haben aber nichts
> miteinander zu tun: Der Docs-Key ist eine Instanz-Umgebungsvariable und öffnet
> ausschließlich die Swagger-/ReDoc-Oberfläche. Ein Org-API-Key funktioniert dort nicht —
> und umgekehrt öffnet der Docs-Key keinen einzigen Datenendpunkt.

Ohne Credential erreichbar sind nur: `GET /health`, `GET /api/version`,
`GET /api/status`, `GET /api/setup/status`, `GET /api/license/mode`,
`GET /api/branding/org/{slug}` sowie die Freigabe-/Track-Routen.

---

## Authentifizierung mit Bearer-Token

### Token erhalten

```http
POST /api/auth/login
Content-Type: application/json

{
  "email": "benutzer@example.com",
  "password": "passwort",
  "org_slug": "jpbg"
}
```

`org_slug` steuert den Geltungsbereich des Tokens:

- **mit `org_slug`** → Token gilt *innerhalb dieser Organisation*, mit der Rolle aus der
  Mitgliedschaft. Das ist der Normalfall für Kolonnen, Fahrzeuge und Tracking.
- **ohne `org_slug`** → Superadmin-Token ohne Org-Bindung. Nur damit erreichst du
  `/api/admin/**` inklusive der [Systemübersicht](#systemübersicht-superadmin).

Antwort:

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

Der Token läuft nach `JWT_EXPIRE_MINUTES` ab (Standard: **7 Tage**). Er wird ungültig,
sobald das Passwort geändert oder das Konto zurückgesetzt wird (Token-Versionierung).

### Mit aktivierter MFA

Ist für das Konto TOTP aktiv, liefert `/api/auth/login` **kein** `access_token`, sondern
eine Zwischenstufe:

```json
{ "mfa_required": true, "mfa_token": "eyJ..." }
```

Diese gegen `POST /api/auth/mfa/verify` mit `{"mfa_token": "…", "code": "123456"}`
eintauschen — erst diese Antwort enthält das `access_token`. Der `mfa_token` allein
öffnet keinen einzigen Endpunkt.

```bash
TOKEN=$(curl -s -X POST https://web.convoyplan.de/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"…"}' | jq -r .access_token)

curl -H "Authorization: Bearer $TOKEN" https://web.convoyplan.de/api/admin/system/overview
```

---

## Authentifizierung mit Org-API-Key

API-Keys sind für **Fremdsysteme** gedacht, die dauerhaft und ohne Benutzerkonto auf die
Daten *einer* Organisation zugreifen — Leitstellen-Anbindung, Dashboard, Skript.

Anlegen im Superadmin-Portal unter **Admin → API-Keys**: Organisation wählen, Name,
Rolle und optionales Ablaufdatum vergeben. Der Klartext wird **genau einmal** angezeigt
(gespeichert wird nur ein bcrypt-Hash) — geht er verloren, muss ein neuer Key her.

**Format:** `cvp_<prefix>_<secret>` — der `prefix` (8 Hex-Zeichen) ist der öffentliche
Nachschlage-Teil und taucht in Portal und Audit-Log auf, das `secret` nie.

```bash
curl -H "X-API-Key: cvp_a1b2c3d4_xxxxxxxx" https://web.convoyplan.de/api/convoys/
```

Eigenschaften:

- Der Key handelt **im Namen des Org-Eigentümers**, aber **immer mit seiner konfigurierten
  Rolle** — auch auf Objekten, die dem Eigentümer selbst gehören. Ein `beobachter`-Key
  kann also nichts ändern, egal wem die Kolonne gehört.
- Wird gleichzeitig ein Bearer-Token gesendet, **gewinnt der API-Key**.
- `last_used_at` wird höchstens alle 5 Minuten fortgeschrieben (ein Schreibzugriff pro
  Request wäre zu teuer) — der Wert ist also grob, nicht sekundengenau.
- Widerrufen wirkt sofort; abgelaufene und widerrufene Keys liefern `401`.

### Welche Endpunkte akzeptieren einen Org-API-Key?

| Bereich | `X-API-Key` | Anmerkung |
|---|---|---|
| `/api/convoys/` — Kolonnen, Fahrzeugzuordnung, Wegpunkte, Teilverbände | ✅ | Rolle des Keys wird durchgesetzt |
| `/api/vehicles/**` | ✅ | ab `planer` schreibend |
| `/api/org/leitstellen/**` | ✅ | |
| `/api/org/branding` | ✅ | |
| Routing, Export/Import, Tankstellen (`/calculate-route`, `/export/*`, …) | ❌ | nur Bearer-Token |
| Tracking und Positionen (`/positions`, `/status`) | ❌ | nur Bearer-Token |
| Freigabelinks (`/share-links`) | ❌ | nur Bearer-Token |
| `/api/organizations/**`, `/api/users/**` | ❌ | nur Bearer-Token |
| `/api/admin/**` inkl. Systemübersicht | ❌ | nur Superadmin-Token |

Ein Org-API-Key auf einem Endpunkt, der keinen akzeptiert, führt zu `401` — nicht zu
einem stillen Fallback auf anonymen Zugriff.

---

## Authentifizierung mit System-API-Key

Ein **System-API-Key** gehört keiner Organisation. Er öffnet ausschließlich die
**lesenden** Endpunkte der Systemübersicht (`GET /api/admin/system/…`) und sonst nichts —
gedacht für Monitoring, Dashboards oder ein Skript, das die Kennzahlen dauerhaft abholen
soll, ohne dass ein Benutzer-Token nach sieben Tagen abläuft.

Anlegen im Superadmin-Portal unter **Admin → API-Keys**, im Auswahlfeld
**Geltungsbereich** den Eintrag *System (instanzweit, nur lesen)* wählen. Format,
einmalige Klartext-Anzeige, Ablauf und Widerruf verhalten sich wie bei Org-Keys; eine
Rolle gibt es nicht, weil es nichts zu schreiben gibt.

```bash
curl -H "X-API-Key: cvp_a1b2c3d4_xxxxxxxx" \
  https://web.convoyplan.de/api/admin/system/overview
```

Die Trennung gilt in beide Richtungen und ist bewusst hart:

- Ein **Org-Key** auf `/api/admin/system/…` → `403`. Die Kennzahlen umfassen die ganze
  Instanz, also alle Mandanten — ein Key, der einer Organisation gehört, darf sie nicht
  sehen.
- Ein **System-Key** auf Kolonnen, Fahrzeuge oder anderen Organisationsdaten → `403`.
- `POST /api/admin/system/sample` verändert den Zustand und bleibt Superadmins
  vorbehalten — ein System-Key erhält dort `401`.
- Alle übrigen `/api/admin/**`-Endpunkte bleiben ebenfalls Superadmins vorbehalten.

Verwaltet werden die Keys über diese Endpunkte (Superadmin-Token erforderlich):

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/admin/system-api-keys` | System-Keys auflisten |
| `POST` | `/api/admin/system-api-keys` | System-Key anlegen (`name`, optional `expires_at`) |
| `DELETE` | `/api/admin/system-api-keys/{key_id}` | System-Key widerrufen |

---

## Rollen im API-Kontext

Dieselbe Hierarchie gilt für Benutzer-Mitgliedschaften und für API-Keys:

| Rolle | Lesen | Position/Status melden | Anlegen & Ändern | Löschen |
|---|---|---|---|---|
| `beobachter` | ✅ | ❌ | ❌ | ❌ |
| `fahrer` | ✅ | ✅ | ❌ | ❌ |
| `planer` | ✅ | ✅ | ✅ | ❌ |
| `admin` | ✅ | ✅ | ✅ | ✅ |

Reicht die Rolle nicht, antwortet die API mit `403` und dem Text
`Insufficient role: requires <rolle>`. Ausführlich: **[Rollen & Berechtigungen](Rollen)**.

---

## Statuscodes und Fehler

| Code | Bedeutung | Typische Ursache |
|---|---|---|
| `401` | nicht authentifiziert | Token fehlt/abgelaufen, Key ungültig, widerrufen oder abgelaufen; auch: Credential am falschen Endpunkt |
| `402` | Demo-Modus | schreibender Zugriff ohne gültige Lizenz (siehe unten) |
| `403` | authentifiziert, aber nicht berechtigt | Rolle zu niedrig, keine Org-Mitgliedschaft, Superadmin nötig, Konto deaktiviert |
| `404` | nicht gefunden | Objekt existiert nicht — oder gehört einer anderen Organisation |
| `422` | Validierungsfehler | fehlende/ungültige Felder (FastAPI-Standardformat) |
| `429` | Drosselung | Rate-Limit oder Stundenkontingent erschöpft — `Retry-After` beachten |

Fehlerantworten haben durchgängig die Form `{"detail": "…"}`; im Demo-Fall zusätzlich
`"demo_mode": true`.

### Drosselung im Detail

**Rate-Limits** (pro IP, gleitendes Fenster) schützen die Anmeldung:
Login und alle MFA-Endpunkte 10 Versuche / 5 Minuten, Passwort-Reset 5 / 15 Minuten,
Tracking-Auth 5 / 5 Minuten, Demo-Sitzungen 10 / Stunde.

**Stundenkontingente** (pro Benutzer) begrenzen Endpunkte, die fremde Dienste oder CPU
kosten — Standardwerte, über `QUOTA_*` konfigurierbar:

| Bereich | Regulär | Demo-Sitzung |
|---|---|---|
| Routenberechnung | 240/h | 40/h |
| Adresssuche (Geocoding) | 600/h | 100/h |
| Live-Verkehrslage | 600/h | 100/h |

Beide Zähler liegen **im Prozessspeicher**: Sie gelten je Worker und werden bei einem
Neustart zurückgesetzt. Als erste Verteidigungslinie gedacht, nicht als harte Abrechnung.

### Demo-Modus (HTTP 402)

Ohne gültigen Lizenzschlüssel läuft die Instanz im Demo-Modus: **GET immer erlaubt**,
`POST`/`PUT`/`PATCH`/`DELETE` auf geschützten Pfaden mit `402` abgewiesen. Ausgenommen
sind `/health`, `/api/auth/login`, `/api/license/*`, `/api/setup`, `/api/track/*` und
`/uploads`. Lesende Integrationen funktionieren also auch unlizenziert.

### Endpunkte

| Methode | Endpunkt | Beschreibung | Auth |
|---|---|---|---|
| `POST` | `/api/auth/register` | Account erstellen | Nein |
| `POST` | `/api/auth/login` | Login, JWT erhalten (optional `org_slug`) | Nein |
| `GET` | `/api/auth/org-lookup` | Organisation zu einem Org-Code auflösen (Login-Maske) | Nein |
| `POST` | `/api/auth/password` | Eigenes Passwort ändern (liefert frisches Token) | Ja |
| `POST` | `/api/auth/password-reset` | Passwort-Reset anstoßen | Nein |
| `POST` | `/api/auth/stream-ticket` | Kurzlebiges Ticket für SSE/WebSocket lösen | Ja |

> SSE- und WebSocket-Verbindungen können keinen `Authorization`-Header setzen. Statt den
> Zugangstoken in die URL zu schreiben, holt man sich über `/api/auth/stream-ticket` ein
> kurzlebiges Ticket und hängt dieses als Query-Parameter an.

### MFA / TOTP

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/auth/mfa/status` | Ist MFA für das eigene Konto aktiv? |
| `POST` | `/api/auth/mfa/setup` | TOTP-Einrichtung starten (QR-Code generieren) |
| `POST` | `/api/auth/mfa/confirm` | TOTP-Einrichtung bestätigen und aktivieren |
| `POST` | `/api/auth/mfa/verify` | `mfa_token` + TOTP-Code gegen vollwertiges JWT tauschen |
| `POST` | `/api/auth/mfa/disable` | MFA deaktivieren |

### Demo-Sitzungen (öffentlich)

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/auth/demo-status` | Ist der öffentliche Demo-Modus aktiviert? |
| `GET` | `/api/auth/demo-session/info` | Rahmendaten einer Demo-Sitzung (Laufzeit) |
| `POST` | `/api/auth/demo-session` | Befristete Demo-Organisation samt Token erzeugen — oder die noch laufende Sitzung dieser IP fortsetzen (`resumed: true`) |

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
| `GET/POST/DELETE` | `/api/admin/system-api-keys` | Instanzweite System-API-Schlüssel verwalten (nur lesend, siehe [oben](#authentifizierung-mit-system-api-key)) |
| `GET` | `/api/branding` | Aktuelles (globales) Branding abrufen |
| `PUT` | `/api/branding` | Globales Branding (Farben, App-Name) aktualisieren |
| `POST` | `/api/branding/logo/{slot}` | Globales Logo hochladen (`slot`: `main` oder `horizontal`) |
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
| `GET/PUT` | `/api/admin/settings/demo` | Demo-Modus an/aus, Sitzungsdauer und Karenzzeit je IP (Stunden) konfigurieren |
| `GET` | `/api/admin/demo-sessions` | Offene Demo-Sitzungen auflisten (Ablaufzeit, Konvoi-Anzahl, Herkunft) |
| `POST` | `/api/admin/demo-sessions/{org_id}/extend` | Ablaufzeit einer Demo-Sitzung verlängern |
| `DELETE` | `/api/admin/demo-sessions/{org_id}` | Demo-Sitzung sofort beenden (Konvois, Org und Demo-Nutzer löschen) |
| `GET` | `/api/admin/demo-ip-locks` | Aktuell gesperrte IP-Adressen mit Restlaufzeit auflisten |
| `DELETE` | `/api/admin/demo-ip-locks/{ip}` | Sperre einer IP-Adresse aufheben |
| `GET` | `/api/admin/demo-ip-allowlist` | Dauerhaft freigestellte Adressen und Netze auflisten |
| `POST` | `/api/admin/demo-ip-allowlist` | Adresse (`203.0.113.7`) oder Netz (`203.0.113.0/24`) dauerhaft freistellen; hebt eine laufende Sperre mit auf |
| `DELETE` | `/api/admin/demo-ip-allowlist/{entry_id}` | Ausnahme zurücknehmen — ab dann gilt wieder die Karenzzeit |

> **Karenzzeit je IP:** `POST /api/auth/demo-session` erlaubt je Client-IP eine Sitzung pro Karenzzeit (Standard 24 h, `DEMO_IP_COOLDOWN_HOURS` bzw. Admin-Portal; `0` schaltet sie ab). Läuft die Karenzzeit noch, **die Sitzung dieser Adresse aber ebenfalls**, wird sie mit einem frischen Token fortgesetzt: Antwort `200` mit `resumed: true` (Audit-Eintrag `demo.session.resumed`) — sonst sperrte die Karenzzeit den Besucher aus seiner eigenen Demo aus, sobald er den Tab schließt. Ist keine Sitzung mehr da, antwortet der Endpunkt mit `429`, `Retry-After` und einem strukturierten `detail`:
>
> ```json
> {"detail": {"message": "Pro IP-Adresse ist alle 24 Stunden …", "reason": "ip_cooldown",
>              "retry_at": "2026-08-14T07:35:12+00:00", "retry_after": 79512, "cooldown_hours": 24}}
> ```
>
> `retry_at` ist der genaue Zeitpunkt der Wiederfreigabe (ISO-8601, UTC) — die Oberfläche zeigt ihn in der Zeitzone des Besuchers an. Die Sperre liegt in der Datenbank (`demo_origins`), übersteht damit einen Neustart und gilt auch dann noch, wenn die Demo-Organisation längst abgelaufen und gelöscht ist. Der Retention-Job entfernt abgelaufene Einträge.

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
die der Reiter **Systemübersicht** im Admin-Portal anzeigt. Details siehe
[Systemübersicht](Systemuebersicht).

Die lesenden Endpunkte akzeptieren **entweder** einen Superadmin-Token **oder** einen
[System-API-Key](#authentifizierung-mit-system-api-key). Das Erfassen einer Stichprobe
verändert den Zustand und erfordert einen Superadmin-Token.

| Methode | Endpunkt | Zugang | Beschreibung |
|---|---|---|---|
| `GET` | `/api/admin/system/overview` | Token **oder** System-Key | Live-Zustand: CPU, RAM, Platten, PSI-Druck, Container, Datenbank, aktive Benutzer |
| `GET` | `/api/admin/system/prtg` | Token **oder** System-Key | Derselbe Live-Zustand im Kanalformat von [PRTG](#anbindung-an-prtg) |
| `GET` | `/api/admin/system/containers` | Token **oder** System-Key | Container-Zustände inkl. Healthcheck und CPU/RAM je Container (`with_stats=true\|false`) |
| `GET` | `/api/admin/system/history` | Token **oder** System-Key | Verlauf (`range=1h…365d` oder `from`/`to`, `resolution=auto\|raw\|hour\|day`, `format=json\|csv`) |
| `GET` | `/api/admin/system/usage` | Token **oder** System-Key | Portalnutzung je Tag (`days=1…1095`) |
| `GET` | `/api/admin/system/reports/months` | Token **oder** System-Key | Monate mit verfügbarem Bericht |
| `GET` | `/api/admin/system/reports/monthly` | Token **oder** System-Key | Monatsbericht (`month=JJJJ-MM`, `format=json\|csv\|pdf`) |
| `POST` | `/api/admin/system/sample` | nur Superadmin-Token | Stichprobe sofort erfassen |

Beispiel — Monatsbericht als PDF holen:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://web.convoyplan.de/api/admin/system/reports/monthly?month=2026-07&format=pdf" \
  -o systembericht-2026-07.pdf
```

Beispiel — Auslastung der letzten 30 Tage für ein Monitoring-System, ohne Login:

```bash
curl -H "X-API-Key: cvp_a1b2c3d4_xxxxxxxx" \
  "https://web.convoyplan.de/api/admin/system/history?range=30d&resolution=hour"
```

Beispiel — CPU-Auslastung als einzelner Wert für einen Uptime-/Metrik-Check:

```bash
curl -sH "X-API-Key: $CVP_SYSTEM_KEY" \
  https://web.convoyplan.de/api/admin/system/overview | jq '.host.cpu_percent'
```

Verlaufsdaten reichen so weit zurück, wie die Aufbewahrung erlaubt: Rohstichproben
90 Tage, verdichtete Tageswerte standardmäßig 3 Jahre. `resolution=auto` wählt
selbstständig zwischen Roh-, Stunden- und Tageswerten, damit die Antwort handlich bleibt.

### Anbindung an PRTG

`GET /api/admin/system/prtg` liefert dieselbe Momentaufnahme wie `/overview`, nur im
Kanalformat des PRTG-Sensortyps **HTTP Data Advanced**. Ein Skript oder ein
Mapping-Template auf der Probe ist dadurch nicht nötig.

Einrichtung in PRTG:

1. Im Superadmin-Portal unter **Admin → API-Keys** einen Key mit Geltungsbereich
   *System* anlegen. Der Klartext wird nur einmal angezeigt.
2. Neuen Sensor **HTTP Data Advanced** an dem Gerät anlegen, das die Instanz vertritt.
3. **URL:** `https://web.convoyplan.de/api/admin/system/prtg`
4. **Custom HTTP Headers:** `X-API-Key: cvp_a1b2c3d4_xxxxxxxx`
5. Abfrageintervall auf 60 s oder mehr stellen — die Momentaufnahme misst die
   CPU-Last über ein kurzes Messfenster und kostet dabei etwas Zeit.

Die Antwort lässt sich vorab prüfen:

```bash
curl -sH "X-API-Key: $CVP_SYSTEM_KEY" \
  https://web.convoyplan.de/api/admin/system/prtg | jq '.prtg.result[].channel'
```

Kanäle der Antwort:

| Bereich | Kanäle |
|---|---|
| Host | CPU-Auslastung, Load 1 min, Load 5 min, Arbeitsspeicher belegt, Arbeitsspeicher verfügbar, Swap belegt, Plattenbelegung, Platte frei, Lese-/Schreibrate, Laufzeit |
| Druck (PSI) | CPU-Druck, Speicher-Druck, I/O-Druck |
| Container | Container gesamt, Container laufend, Container gestört |
| Datenbank | Datenbankgröße, Datenbankverbindungen |
| Nutzung | Aktive Benutzer, Aktive Demo-Besucher, Eindeutige Benutzer heute, Anmeldungen 24 h, Antwortzeit Ø |
| Erfassung | Alter der letzten Stichprobe |

Zu Auslastung, Druck und gestörten Containern liefert die Antwort Warn- und
Fehlergrenzen mit. PRTG übernimmt sie beim Anlegen der Kanäle; wer sie danach in den
Kanaleinstellungen ändert, behält seine eigenen Werte.

Nicht jeder Kanal erscheint auf jeder Instanz:

- **PSI-Kanäle** fehlen, wenn der Kernel keine Druckwerte liefert.
- **Container-Kanäle** fehlen, solange die Docker-API nicht erreichbar ist — statt
  dreier Nullen, die wie ein toter Stack aussähen, steht der Grund im Sensortext.
- **Alter der letzten Stichprobe** fehlt, solange der Collector abgeschaltet ist
  (`SYSTEM_METRICS_ENABLED=false`) oder noch nie gemessen hat.

Ein Kennwert, den der Host grundsätzlich nicht messen kann, fehlt dauerhaft — das ist
Absicht: PRTG erkennt Kanäle am Namen, und Kanäle, die kommen und gehen, zerreißen den
Verlauf.

Lässt sich überhaupt nichts messen, antwortet der Endpunkt mit dem Fehlerformat des
Sensors (`{"prtg": {"error": 1, "text": "…"}}`) statt mit HTTP 500, damit in PRTG der
Grund und nicht nur „Server Error" am Sensor steht. Ein falscher oder fehlender Key
bleibt ein `401`, ein Org-Key ein `403`.

Für einen reinen Erreichbarkeitscheck genügt ohne Key ein HTTP-Sensor auf `/health`
oder `/api/status`.

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
