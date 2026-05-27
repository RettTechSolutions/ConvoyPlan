# Dashboard Overlays Design

**Datum:** 2026-05-06  
**Scope:** Wetter · OSM-Straßensperren · erweiterter Servicestatus · aktive Nutzer (SSE)

---

## Ziel

Eine zentrierte Top-Pill (`InfoPill`) ersetzt die bisherigen getrennten Widgets (`ServiceStatus`, `WeatherWidget`). Sie zeigt auf einen Blick: aktuelles Wetter am Startort des gewählten Konvois, Gesundheitsstatus aller externen Dienste, Anzahl aktiver Nutzer (Echtzeit via SSE) und Anzahl gefundener Straßensperren. Bei Klick klappt ein Detailpanel auf.

---

## Architektur

### Backend — drei Erweiterungen

**1. `/api/users/online` — SSE-Endpoint** (`backend/app/api/routes/users.py`, neu)

- `Content-Type: text/event-stream`
- Jede eingehende Verbindung legt eine `asyncio.Queue` in einem globalen `_connections: set[Queue]` ab.
- Beim Connect: aktuelle Zahl (`len(_connections)`) sofort als `data: {"count": N}\n\n` pushen.
- Beim Disconnect (GeneratorExit / CancelledError): Queue aus Set entfernen, allen verbleibenden Clients neuen Count pushen.
- Keepalive-Kommentar alle 30 s: `: keepalive\n\n`
- Kein Auth. Count ist siteweiter Wert (alle offenen Browser-Sessions).

**2. Service-Cache in Weather + Overpass** (`backend/app/services/weather.py`, `overpass.py`)

Jeder Service hält ein Modul-Level-Dict:
```python
_last_check: dict = {"status": "unknown", "latency_ms": None, "checked_at": None}
```
Jeder echte Netzwerk-Call updatet dieses Dict (Status `"ok"` / `"error"`, Latenz in ms, Timestamp). Eine öffentliche Funktion `last_check() -> dict` gibt es zurück.

**3. `/api/status` erweitert** (`backend/app/api/routes/status.py`)

Zwei neue Felder in der Antwort:
```json
"weather_api": {"status": "ok", "latency_ms": 42, "checked_at": "..."},
"overpass_api": {"status": "unknown", "latency_ms": null, "checked_at": null}
```
`"unknown"` solange noch kein echter Call lief. Status-Endpoint fragt selbst **nicht** live an — liest nur den Cache.

`backend/app/main.py` — `users`-Router registrieren.

---

### Frontend — neue InfoPill-Komponente

**`frontend/src/lib/components/InfoPill.svelte`** (neu, ersetzt `ServiceStatus.svelte` + `WeatherWidget.svelte`)

Props:
```typescript
interface Props {
  startPoint?: { lat: number; lon: number } | null;  // für Wetterabruf
  closuresCount?: number;                             // Anzahl gefundener Sperren
  onShowClosures?: () => void;                        // Callback: auf Karte anzeigen
}
```

Interner State:
- `status` — pollt `/api/status` alle 30 s
- `weather` — einmalig abgerufen wenn `startPoint` gesetzt, gecacht
- `onlineCount` — SSE-Subscription auf `/api/users/online`, Auto-Reconnect nach 5 s
- `expanded` — boolean für aufgeklapptes Panel

Collapsed-Zustand (immer sichtbar, zentriert oben):
```
[Wetter-Icon] [Temp]°C · [●●●●●] · [👥 N] · [⚠ N Sperren]  (wenn Sperren > 0)
```

Expanded-Panel (klappt unterhalb der Pill auf):
- Links: Dienste-Liste (Backend, DB, Routing, Wetter-API, Sperren-API) mit Dot + Name + Status/Latenz
- Rechts oben: Wetter-Detail (Icon, Temp, Wind, 4-Stunden-Forecast)
- Rechts unten: Aktive Nutzer (große Zahl)
- Unten: Straßensperren-Sektion (Liste der gefundenen Einträge + Button "Auf Karte anzeigen")

**`frontend/src/lib/api/index.ts`** — Erweiterungen:
```typescript
// StatusResponse erweitern:
export interface ServiceCheck {
  status: 'ok' | 'error' | 'unknown';
  latency_ms: number | null;
  checked_at: string | null;
}
export interface StatusResponse {
  checked_at: string;
  backend: 'ok' | 'error';
  database: 'ok' | 'error';
  graphhopper: 'ok' | 'building' | 'offline';
  graphhopper_bbox: number[] | null;
  weather_api: ServiceCheck;
  overpass_api: ServiceCheck;
}

// SSE-Helper:
export const usersApi = {
  onlineStream: () => new EventSource('/api/users/online'),
};
```

**`frontend/src/routes/plan/+page.svelte`** — Änderungen:
- Import `ServiceStatus` + `WeatherWidget` entfernen, durch `InfoPill` ersetzen
- `InfoPill` bekommt `startPoint={selected?.start_point}` und `closuresCount={closures?.features?.length ?? 0}`
- Wetter-Abruf aus `+page.svelte` entfernen (InfoPill macht das selbst)
- `closures`-State bleibt — InfoPill bekommt `onShowClosures` Callback der `showClosures = true` setzt

---

## Closures-Flow

1. Wenn ein Konvoi mit `start_point` geladen wird → InfoPill ruft automatisch `/api/weather/` ab.
2. Closures werden **nicht** automatisch geladen — Nutzer klickt "Auf Karte anzeigen" im Panel.
3. `+page.svelte` ruft dann `overpassApi.getClosures(lat, lon)` ab und übergibt das Result an `MapView`.
4. MapView rendert Closures als rote Layer (bereits implementiert via `closuresGeojson`-Prop).

---

## Dateiübersicht

| Datei | Änderung |
|-------|----------|
| `backend/app/api/routes/users.py` | NEU — SSE-Endpoint |
| `backend/app/services/weather.py` | +Cache-Dict, `last_check()` |
| `backend/app/services/overpass.py` | +Cache-Dict, `last_check()` |
| `backend/app/api/routes/status.py` | +`weather_api`, `overpass_api` Felder |
| `backend/app/main.py` | +`users`-Router |
| `frontend/src/lib/api/index.ts` | +`StatusResponse`, `ServiceCheck`, `usersApi` |
| `frontend/src/lib/components/InfoPill.svelte` | NEU — ersetzt ServiceStatus + WeatherWidget |
| `frontend/src/routes/plan/+page.svelte` | Import-Swap, InfoPill-Props verdrahten |

---

## Fehlerbehandlung

- SSE-Verbindung bricht ab → nach 5 s Auto-Reconnect (EventSource macht das automatisch)
- Backend-Neustart → `onlineCount` geht auf 0, steigt sofort wieder wenn Clients reconnecten
- Weather-API nicht erreichbar → `weather_api.status = "error"` im Cache, InfoPill zeigt grauen Dot
- Overpass-Timeout → `overpass_api.status = "error"`, Sperren-Abruf zeigt Fehlermeldung

---

## Nicht in Scope

- Per-Konvoi-Nutzerzahl (nur siteweiter Count)
- Push-Benachrichtigungen bei Sperren
- Kommerzieller Echtzeit-Verkehrsdienst
- Persistenz des Online-Counts über Backend-Neustarts hinaus
