# Dashboard Overlays Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine zentrierte `InfoPill`-Komponente zeigt Wetter (Startort), Servicestatus aller externen Dienste, aktive Nutzer (SSE, echtzeit) und Straßensperren-Count.

**Architecture:** Neuer SSE-Endpoint `/api/users/online` hält In-Memory-Verbindungen, pusht Count bei Connect/Disconnect. Weather- und Overpass-Services cachen ihren letzten Aufrufstatus; der `/api/status`-Endpoint liest nur den Cache. `InfoPill.svelte` ersetzt `ServiceStatus.svelte` + `WeatherWidget.svelte`.

**Tech Stack:** FastAPI `StreamingResponse` (SSE), asyncio.Queue, Svelte 5 `$state`/`$effect`/`onMount`/`onDestroy`, `EventSource` API.

---

## File Map

| Datei | Änderung |
|-------|----------|
| `backend/app/api/routes/users.py` | NEU — SSE-Endpoint `/users/online` |
| `backend/app/main.py` | +`users`-Router |
| `backend/app/services/weather.py` | +`_last_check` Cache, `last_check()`, Cache-Update in `get_weather()` |
| `backend/app/services/overpass.py` | +`_last_check` Cache, `last_check()`, Cache-Update in `get_closures()` |
| `backend/app/api/routes/status.py` | +`weather_api` + `overpass_api` Felder (Datei ist untracked — wird committed) |
| `frontend/src/lib/api/index.ts` | +`ServiceCheck`, `StatusResponse`, `statusApi`, `usersApi` |
| `frontend/src/lib/components/InfoPill.svelte` | NEU — ersetzt ServiceStatus + WeatherWidget |
| `frontend/src/routes/plan/+page.svelte` | Import-Swap, InfoPill verdrahten, `toggleClosures` nutzt Startpunkt |

---

### Task 1: Backend — SSE Users Endpoint

**Files:**
- Create: `backend/app/api/routes/users.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: `users.py` erstellen**

  ```python
  import asyncio
  import json
  from fastapi import APIRouter
  from fastapi.responses import StreamingResponse

  router = APIRouter(prefix="/users", tags=["users"])

  _connections: set[asyncio.Queue] = set()


  async def _broadcast(count: int) -> None:
      msg = f"data: {json.dumps({'count': count})}\n\n"
      for q in list(_connections):
          await q.put(msg)


  @router.get("/online")
  async def online_users() -> StreamingResponse:
      queue: asyncio.Queue = asyncio.Queue()
      _connections.add(queue)
      await _broadcast(len(_connections))

      async def stream():
          try:
              yield f"data: {json.dumps({'count': len(_connections)})}\n\n"
              while True:
                  try:
                      msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                      yield msg
                  except asyncio.TimeoutError:
                      yield ": keepalive\n\n"
          except (GeneratorExit, asyncio.CancelledError):
              pass
          finally:
              _connections.discard(queue)
              await _broadcast(len(_connections))

      return StreamingResponse(
          stream(),
          media_type="text/event-stream",
          headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
      )
  ```

- [ ] **Step 2: Router in `main.py` registrieren**

  In `backend/app/main.py` die Import-Zeile finden:
  ```python
  from app.api.routes import auth, convoys, vehicles, routing, organizations, tracking, lage, weather, overpass, status
  ```
  Ersetzen durch:
  ```python
  from app.api.routes import auth, convoys, vehicles, routing, organizations, tracking, lage, weather, overpass, status, users
  ```

  Nach `app.include_router(status.router, prefix="/api")` einfügen:
  ```python
  app.include_router(users.router, prefix="/api")
  ```

- [ ] **Step 3: Backend neu starten und SSE manuell testen**

  ```bash
  cd /Users/working_chris/GitHub/MarschPlan
  docker compose restart backend
  sleep 3
  curl -s http://localhost:8000/health
  ```
  Expected: `{"status":"ok","version":"0.2.0"}`

  ```bash
  curl -N http://localhost:8000/api/users/online
  ```
  Expected: `data: {"count": 1}` (sofort, dann `: keepalive` alle 30 s, Ctrl+C zum Beenden).

- [ ] **Step 4: Commit**

  ```bash
  git add backend/app/api/routes/users.py backend/app/main.py
  git commit -m "feat(users): SSE endpoint for real-time online user count"
  ```

---

### Task 2: Backend — Service-Health-Cache in Weather + Overpass

**Files:**
- Modify: `backend/app/services/weather.py`
- Modify: `backend/app/services/overpass.py`

- [ ] **Step 1: Cache zu `weather.py` hinzufügen**

  Die aktuelle Datei `backend/app/services/weather.py` lesen. Am Anfang nach den Imports einfügen:

  ```python
  import time
  from datetime import datetime, timezone
  ```

  Nach der `WMO_CODES`-Dict-Definition (vor `async def get_weather`) einfügen:

  ```python
  _last_check: dict = {"status": "unknown", "latency_ms": None, "checked_at": None}


  def last_check() -> dict:
      return dict(_last_check)
  ```

  Die Funktion `get_weather` vollständig ersetzen durch:

  ```python
  async def get_weather(lat: float, lon: float) -> dict:
      global _last_check
      params = {
          "latitude": lat,
          "longitude": lon,
          "current_weather": True,
          "hourly": "temperature_2m,precipitation_probability,weathercode,windspeed_10m",
          "forecast_days": 1,
          "timezone": "Europe/Berlin",
      }
      t0 = time.monotonic()
      try:
          async with httpx.AsyncClient(timeout=10.0) as client:
              resp = await client.get(OPEN_METEO_URL, params=params)
              resp.raise_for_status()
              data = resp.json()
          _last_check = {
              "status": "ok",
              "latency_ms": round((time.monotonic() - t0) * 1000),
              "checked_at": datetime.now(timezone.utc).isoformat(),
          }
      except Exception:
          _last_check = {
              "status": "error",
              "latency_ms": None,
              "checked_at": datetime.now(timezone.utc).isoformat(),
          }
          raise

      cw = data.get("current_weather", {})
      hourly = data.get("hourly", {})
      hours = hourly.get("time", [])
      temps = hourly.get("temperature_2m", [])
      precip = hourly.get("precipitation_probability", [])
      wcodes = hourly.get("weathercode", [])

      forecast = [
          {
              "time": hours[i],
              "temp_c": temps[i],
              "precip_pct": precip[i],
              "condition": WMO_CODES.get(wcodes[i], "Unbekannt"),
          }
          for i in range(min(len(hours), 12))
      ]

      return {
          "current": {
              "temp_c": cw.get("temperature"),
              "windspeed_kmh": cw.get("windspeed"),
              "condition": WMO_CODES.get(cw.get("weathercode", -1), "Unbekannt"),
              "is_day": cw.get("is_day", 1) == 1,
          },
          "hourly_forecast": forecast,
      }
  ```

- [ ] **Step 2: Cache zu `overpass.py` hinzufügen**

  In `backend/app/services/overpass.py` nach den Imports (`import httpx`) einfügen:

  ```python
  import time
  from datetime import datetime, timezone

  _last_check: dict = {"status": "unknown", "latency_ms": None, "checked_at": None}


  def last_check() -> dict:
      return dict(_last_check)
  ```

  Die Funktion `get_closures` vollständig ersetzen durch:

  ```python
  async def get_closures(lat: float, lon: float, radius_m: int = 15000) -> dict:
      global _last_check
      query = _build_query(lat, lon, radius_m)
      t0 = time.monotonic()
      try:
          async with httpx.AsyncClient(timeout=30.0) as client:
              resp = await client.post(OVERPASS_URL, data={"data": query})
              resp.raise_for_status()
              data = resp.json()
          _last_check = {
              "status": "ok",
              "latency_ms": round((time.monotonic() - t0) * 1000),
              "checked_at": datetime.now(timezone.utc).isoformat(),
          }
      except Exception:
          _last_check = {
              "status": "error",
              "latency_ms": None,
              "checked_at": datetime.now(timezone.utc).isoformat(),
          }
          raise

      return _to_geojson(data.get("elements", []))
  ```

- [ ] **Step 3: Import-Check**

  ```bash
  docker compose exec backend python -c "
  from app.services.weather import last_check as wlc
  from app.services.overpass import last_check as olc
  print('weather:', wlc())
  print('overpass:', olc())
  "
  ```
  Expected:
  ```
  weather: {'status': 'unknown', 'latency_ms': None, 'checked_at': None}
  overpass: {'status': 'unknown', 'latency_ms': None, 'checked_at': None}
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add backend/app/services/weather.py backend/app/services/overpass.py
  git commit -m "feat(status): add health cache to weather and overpass services"
  ```

---

### Task 3: Backend — `/api/status` um weather_api + overpass_api erweitern

**Files:**
- Modify: `backend/app/api/routes/status.py` (Datei ist aktuell **untracked** — existiert im Arbeitsverzeichnis, aber nicht in git)

- [ ] **Step 1: Datei lesen**

  Die aktuelle `backend/app/api/routes/status.py` lesen. Sie enthält bereits Checks für DB und GraphHopper.

- [ ] **Step 2: Imports erweitern**

  Import-Zeile suchen:
  ```python
  from app.config import settings
  from app.database import get_db
  ```
  Nach diesen Zeilen einfügen:
  ```python
  from app.services import weather as weather_svc
  from app.services import overpass as overpass_svc
  ```

- [ ] **Step 3: Return-Dict erweitern**

  Den `return {…}`-Block am Ende des Endpoints finden:
  ```python
      return {
          "checked_at": datetime.now(timezone.utc).isoformat(),
          "backend": "ok",
          "database": "ok" if db_ok else "error",
          "graphhopper": gh_status,
          "graphhopper_bbox": gh_bbox,
      }
  ```

  Ersetzen durch:
  ```python
      return {
          "checked_at": datetime.now(timezone.utc).isoformat(),
          "backend": "ok",
          "database": "ok" if db_ok else "error",
          "graphhopper": gh_status,
          "graphhopper_bbox": gh_bbox,
          "weather_api": weather_svc.last_check(),
          "overpass_api": overpass_svc.last_check(),
      }
  ```

- [ ] **Step 4: Prüfen**

  ```bash
  docker compose restart backend
  sleep 3
  curl -s http://localhost:8000/api/status | python3 -m json.tool | grep -A3 "weather_api\|overpass_api"
  ```
  Expected:
  ```json
  "weather_api": {
      "status": "unknown",
      "latency_ms": null,
      "checked_at": null
  },
  "overpass_api": {
      "status": "unknown",
      "latency_ms": null,
      "checked_at": null
  }
  ```

- [ ] **Step 5: Commit (inkl. bisher untracked status.py)**

  ```bash
  git add backend/app/api/routes/status.py
  git commit -m "feat(status): add weather_api and overpass_api health to status endpoint"
  ```

---

### Task 4: Frontend — API-Typen und Clients erweitern

**Files:**
- Modify: `frontend/src/lib/api/index.ts`

- [ ] **Step 1: `ServiceCheck` + `StatusResponse` hinzufügen**

  In `frontend/src/lib/api/index.ts` nach `export interface WeatherResponse {…}` (ca. Zeile 92) einfügen:

  ```typescript
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
  ```

- [ ] **Step 2: `statusApi` + `usersApi` hinzufügen**

  Nach `export const weatherApi = {…}` (ca. Zeile 175) einfügen:

  ```typescript
  // V3: Status
  export const statusApi = {
    get: () => api.get<StatusResponse>('/api/status'),
  };

  // V3: Online Users (SSE)
  export const usersApi = {
    onlineStream: (): EventSource =>
      new EventSource(
        `${import.meta.env.VITE_API_URL ?? 'http://localhost:8000'}/api/users/online`
      ),
  };
  ```

- [ ] **Step 3: TypeScript prüfen**

  ```bash
  cd /Users/working_chris/GitHub/MarschPlan/frontend && npx tsc --noEmit 2>&1 | head -20
  ```
  Expected: keine neuen Fehler.

- [ ] **Step 4: Commit**

  ```bash
  git add frontend/src/lib/api/index.ts
  git commit -m "feat(api): add StatusResponse, ServiceCheck, statusApi, usersApi types"
  ```

---

### Task 5: Frontend — `InfoPill.svelte` erstellen

**Files:**
- Create: `frontend/src/lib/components/InfoPill.svelte`

- [ ] **Step 1: Datei erstellen**

  ```svelte
  <script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { weatherApi, statusApi, usersApi, type StatusResponse, type WeatherResponse } from '$lib/api';

    interface Props {
      startPoint?: { lat: number; lon: number } | null;
      closuresCount?: number;
      onShowClosures?: () => void;
    }

    let { startPoint = null, closuresCount = 0, onShowClosures }: Props = $props();

    let status = $state<StatusResponse | null>(null);
    let weather = $state<WeatherResponse | null>(null);
    let onlineCount = $state(0);
    let expanded = $state(false);
    let weatherLoading = $state(false);

    let pollInterval: ReturnType<typeof setInterval>;
    let sse: EventSource | null = null;

    // ── Status polling ───────────────────────────────────────────────
    async function fetchStatus() {
      try {
        status = await statusApi.get();
      } catch { /* ignore — shows as null */ }
    }

    // ── SSE for online count ─────────────────────────────────────────
    function connectSSE() {
      if (sse) { sse.close(); }
      sse = usersApi.onlineStream();
      sse.onmessage = (e) => {
        try { onlineCount = JSON.parse(e.data).count ?? 0; } catch { /* ignore */ }
      };
      sse.onerror = () => {
        sse?.close();
        setTimeout(connectSSE, 5000);
      };
    }

    // ── Weather fetch when startPoint changes ────────────────────────
    $effect(() => {
      if (startPoint?.lat && startPoint?.lon) {
        weatherLoading = true;
        weatherApi.get(startPoint.lat, startPoint.lon)
          .then(w => { weather = w; })
          .catch(() => { weather = null; })
          .finally(() => { weatherLoading = false; });
      } else {
        weather = null;
      }
    });

    onMount(() => {
      fetchStatus();
      pollInterval = setInterval(fetchStatus, 30_000);
      connectSSE();
    });

    onDestroy(() => {
      clearInterval(pollInterval);
      sse?.close();
    });

    // ── Helpers ──────────────────────────────────────────────────────
    const WMO_ICONS: Record<string, string> = {
      'Klar': '☀️', 'Überwiegend klar': '🌤️', 'Teils bewölkt': '⛅',
      'Bewölkt': '☁️', 'Nebel': '🌫️', 'Raureif': '🌫️',
      'Leichter Nieselregen': '🌦️', 'Nieselregen': '🌧️', 'Starker Nieselregen': '🌧️',
      'Leichter Regen': '🌧️', 'Regen': '🌧️', 'Starker Regen': '⛈️',
      'Leichter Schnee': '🌨️', 'Schnee': '❄️', 'Starker Schnee': '❄️',
      'Leichte Schauer': '🌦️', 'Schauer': '🌧️', 'Starke Schauer': '⛈️',
      'Gewitter': '⛈️', 'Gewitter mit Hagel': '⛈️', 'Schweres Gewitter mit Hagel': '⛈️',
    };
    function wIcon(c: string) { return WMO_ICONS[c] ?? '🌡️'; }

    type DotColor = 'ok' | 'warn' | 'err' | 'unknown';
    function svcColor(s: string | undefined): DotColor {
      if (s === 'ok') return 'ok';
      if (s === 'building') return 'warn';
      if (s === 'unknown') return 'unknown';
      return 'err';
    }

    const GH_LABEL: Record<string, string> = {
      ok: 'Bereit', building: 'Karte wird geladen…', offline: 'Offline',
    };

    function relTime(iso: string | null): string {
      if (!iso) return '';
      const diff = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
      if (diff < 5) return 'gerade eben';
      if (diff < 60) return `vor ${diff} s`;
      return `vor ${Math.round(diff / 60)} min`;
    }

    $derived: const overallOk =
      !status ||
      status.backend === 'error' ||
      status.database === 'error' ||
      status.graphhopper === 'offline' ||
      status.weather_api?.status === 'error' ||
      status.overpass_api?.status === 'error';
  </script>

  <div class="pill-wrap">
    <!-- ── Collapsed pill ── -->
    <button
      class="pill"
      class:has-closures={closuresCount > 0}
      onclick={() => (expanded = !expanded)}
    >
      {#if weather && !weatherLoading}
        <span class="pill-ico">{wIcon(weather.current.condition)}</span>
        <span class="pill-temp">{weather.current.temp_c?.toFixed(0)}°C</span>
        <span class="pill-sep">·</span>
      {:else if weatherLoading}
        <span class="pill-ico">⏳</span>
        <span class="pill-sep">·</span>
      {/if}

      <span class="pill-dots">
        <span class="dot {svcColor(status?.backend)}" title="Backend"></span>
        <span class="dot {svcColor(status?.database)}" title="Datenbank"></span>
        <span class="dot {svcColor(status?.graphhopper)}" title="Routing"></span>
        <span class="dot {svcColor(status?.weather_api?.status)}" title="Wetter-API"></span>
        <span class="dot {svcColor(status?.overpass_api?.status)}" title="Sperren-API"></span>
      </span>

      <span class="pill-sep">·</span>
      <span class="pill-users">👥 {onlineCount}</span>

      {#if closuresCount > 0}
        <span class="pill-sep">·</span>
        <span class="pill-closures">⚠ {closuresCount} Sperren</span>
      {/if}
    </button>

    <!-- ── Expanded panel ── -->
    {#if expanded}
      <div class="panel">
        <div class="panel-header">
          <strong>Systemstatus</strong>
          {#if status?.checked_at}
            <span class="panel-time">Aktualisiert {relTime(status.checked_at)}</span>
          {/if}
          <button class="close-btn" onclick={() => (expanded = false)}>✕</button>
        </div>

        <div class="panel-grid">
          <!-- Services column -->
          <div class="svc-list">
            <div class="col-label">Dienste</div>
            <div class="svc-row">
              <span class="dot {svcColor(status?.backend)}"></span>
              <span class="svc-name">Backend API</span>
              <span class="svc-val {svcColor(status?.backend)}">
                {status?.backend === 'ok' ? 'OK' : 'Fehler'}
              </span>
            </div>
            <div class="svc-row">
              <span class="dot {svcColor(status?.database)}"></span>
              <span class="svc-name">Datenbank</span>
              <span class="svc-val {svcColor(status?.database)}">
                {status?.database === 'ok' ? 'OK' : 'Fehler'}
              </span>
            </div>
            <div class="svc-row">
              <span class="dot {svcColor(status?.graphhopper)}" class:pulse={status?.graphhopper === 'building'}></span>
              <span class="svc-name">Routing</span>
              <span class="svc-val {svcColor(status?.graphhopper)}">
                {GH_LABEL[status?.graphhopper ?? 'offline'] ?? 'Offline'}
              </span>
            </div>
            <div class="svc-row">
              <span class="dot {svcColor(status?.weather_api?.status)}"></span>
              <span class="svc-name">Wetter (open-meteo)</span>
              <span class="svc-val {svcColor(status?.weather_api?.status)}">
                {status?.weather_api?.status === 'ok'
                  ? `${status.weather_api.latency_ms} ms`
                  : (status?.weather_api?.status ?? '–')}
              </span>
            </div>
            <div class="svc-row">
              <span class="dot {svcColor(status?.overpass_api?.status)}"></span>
              <span class="svc-name">Sperren (Overpass)</span>
              <span class="svc-val {svcColor(status?.overpass_api?.status)}">
                {status?.overpass_api?.status === 'ok'
                  ? `${status.overpass_api.latency_ms} ms`
                  : (status?.overpass_api?.status ?? '–')}
              </span>
            </div>
          </div>

          <!-- Right column: weather + users -->
          <div class="right-col">
            <!-- Weather -->
            <div class="weather-block">
              <div class="col-label">Wetter{startPoint ? ' — Startort' : ''}</div>
              {#if weather}
                <div class="weather-main">
                  <span class="w-ico">{wIcon(weather.current.condition)}</span>
                  <div>
                    <div class="w-temp">{weather.current.temp_c?.toFixed(0)}°C</div>
                    <div class="w-sub">{weather.current.condition} · 💨 {weather.current.windspeed_kmh?.toFixed(0)} km/h</div>
                  </div>
                </div>
                <div class="forecast">
                  {#each weather.hourly_forecast.slice(0, 4) as h}
                    <div class="fc-hour">
                      <div class="fc-time">{h.time.slice(11, 16)}</div>
                      <div class="fc-ico">{wIcon(h.condition)}</div>
                      <div class="fc-temp">{h.temp_c?.toFixed(0)}°</div>
                      <div class="fc-precip">{h.precip_pct ?? 0}%</div>
                    </div>
                  {/each}
                </div>
              {:else if !startPoint}
                <p class="hint-sm">Konvoi mit Startpunkt wählen</p>
              {:else}
                <p class="hint-sm">Wetterdaten laden…</p>
              {/if}
            </div>

            <!-- Users -->
            <div class="users-block">
              <div class="col-label">Aktive Nutzer</div>
              <div class="users-count">
                <span class="users-ico">👥</span>
                <span class="users-num">{onlineCount}</span>
                <span class="users-label">gerade online</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Closures -->
        {#if closuresCount > 0 || onShowClosures}
          <div class="closures-block">
            <div class="closures-header">
              <div class="col-label">Straßensperren</div>
              {#if closuresCount > 0}
                <span class="closures-badge">{closuresCount} gefunden</span>
              {/if}
            </div>
            {#if onShowClosures}
              <button class="btn-show-closures" onclick={() => { onShowClosures?.(); expanded = false; }}>
                Auf Karte anzeigen ↗
              </button>
            {/if}
          </div>
        {/if}
      </div>
    {/if}
  </div>

  <style>
    .pill-wrap {
      position: absolute;
      top: 14px;
      left: 50%;
      transform: translateX(-50%);
      z-index: 500;
      display: flex;
      flex-direction: column;
      align-items: center;
    }

    .pill {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 7px 16px;
      background: rgba(20, 32, 60, 0.92);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(255, 255, 255, .18);
      border-radius: 24px;
      color: white;
      font-size: 11px;
      cursor: pointer;
      white-space: nowrap;
      box-shadow: 0 2px 12px rgba(0, 0, 0, .35);
      transition: background .15s;
    }
    .pill:hover { background: rgba(20, 32, 60, .98); }

    .pill-ico { font-size: 14px; }
    .pill-temp { font-weight: 700; font-size: 13px; }
    .pill-sep { color: rgba(255, 255, 255, .3); }
    .pill-dots { display: flex; align-items: center; gap: 4px; }
    .pill-users { font-size: 11px; }
    .pill-closures {
      background: #c0392b;
      border-radius: 10px;
      padding: 2px 8px;
      font-size: 9px;
      font-weight: 600;
    }

    /* Dot colours */
    .dot {
      display: inline-block;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    .dot.ok { background: #27ae60; }
    .dot.warn { background: #f39c12; }
    .dot.err { background: #e74c3c; }
    .dot.unknown { background: #6b7177; }

    /* Panel */
    .panel {
      margin-top: 6px;
      background: rgba(15, 27, 53, 0.97);
      backdrop-filter: blur(10px);
      border: 1px solid rgba(255, 255, 255, .15);
      border-radius: 12px;
      padding: 14px 16px;
      color: white;
      font-size: 11px;
      box-shadow: 0 8px 30px rgba(0, 0, 0, .5);
      min-width: 420px;
    }

    .panel-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 12px;
      font-size: 12px;
    }
    .panel-time { flex: 1; color: rgba(255,255,255,.35); font-size: 9px; }
    .close-btn {
      background: none; border: none; color: rgba(255,255,255,.4);
      cursor: pointer; font-size: .85rem; padding: 0; line-height: 1;
    }
    .close-btn:hover { color: white; }

    .panel-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0 20px;
    }

    .col-label {
      font-size: 9px;
      text-transform: uppercase;
      letter-spacing: .06em;
      color: rgba(255,255,255,.4);
      margin-bottom: 6px;
    }

    /* Services */
    .svc-list { display: flex; flex-direction: column; gap: 5px; }
    .svc-row { display: flex; align-items: center; gap: 6px; }
    .svc-name { flex: 1; color: rgba(255,255,255,.65); }
    .svc-val { font-weight: 600; font-size: 10px; }
    .svc-val.ok { color: #2ecc71; }
    .svc-val.warn { color: #f39c12; }
    .svc-val.err { color: #e74c3c; }
    .svc-val.unknown { color: #6b7177; }

    /* Weather */
    .weather-block { margin-bottom: 10px; }
    .weather-main { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
    .w-ico { font-size: 22px; }
    .w-temp { font-weight: 700; font-size: 16px; }
    .w-sub { color: rgba(255,255,255,.55); font-size: 9px; }
    .forecast { display: flex; gap: 5px; }
    .fc-hour {
      text-align: center; font-size: 8px; color: rgba(255,255,255,.6);
      background: rgba(255,255,255,.06); border-radius: 4px; padding: 3px 5px;
      display: flex; flex-direction: column; align-items: center; gap: 1px;
    }
    .fc-time { color: rgba(255,255,255,.5); }
    .fc-ico { font-size: 10px; }
    .fc-temp { font-weight: 600; }
    .fc-precip { color: #74b9ff; }

    /* Users */
    .users-block {
      background: rgba(255,255,255,.05);
      border-radius: 6px;
      padding: 8px;
    }
    .users-count { display: flex; align-items: center; gap: 6px; }
    .users-ico { font-size: 18px; }
    .users-num { font-weight: 700; font-size: 20px; }
    .users-label { color: rgba(255,255,255,.45); font-size: 9px; }

    /* Closures */
    .closures-block {
      margin-top: 12px;
      border-top: 1px solid rgba(255,255,255,.08);
      padding-top: 10px;
    }
    .closures-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
    .closures-badge {
      background: #c0392b; border-radius: 10px;
      padding: 2px 8px; font-size: 9px; font-weight: 600;
    }
    .btn-show-closures {
      background: rgba(255,255,255,.1); border: none;
      color: rgba(255,255,255,.75); border-radius: 5px;
      padding: 4px 10px; font-size: 9px; cursor: pointer;
    }
    .btn-show-closures:hover { background: rgba(255,255,255,.18); color: white; }

    .hint-sm { color: rgba(255,255,255,.35); font-size: 9px; margin: 4px 0 0; }

    @keyframes pulse-ring {
      0% { box-shadow: 0 0 0 0 rgba(243,156,18,.6); }
      70% { box-shadow: 0 0 0 4px rgba(243,156,18,0); }
      100% { box-shadow: 0 0 0 0 rgba(243,156,18,0); }
    }
    .pulse { animation: pulse-ring 1.4s ease-out infinite; }
  </style>
  ```

  > **Hinweis zu `$derived`:** Die Zeile `$derived: const overallOk = …` im Script-Block ist Svelte 5 Syntax. Falls der TypeScript-Checker das ablehnt, alternative Syntax: `const overallOk = $derived(…)`.

- [ ] **Step 2: TypeScript prüfen**

  ```bash
  cd /Users/working_chris/GitHub/MarschPlan/frontend && npx tsc --noEmit 2>&1 | head -30
  ```
  Expected: keine Fehler (oder nur vorbestehende Fehler, die nicht mit InfoPill zusammenhängen).

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/src/lib/components/InfoPill.svelte
  git commit -m "feat(ui): add InfoPill component with weather, status, users, closures"
  ```

---

### Task 6: Frontend — InfoPill in `+page.svelte` verdrahten

**Files:**
- Modify: `frontend/src/routes/plan/+page.svelte`

- [ ] **Step 1: Imports aktualisieren**

  Datei lesen. Die aktuellen Imports finden:
  ```svelte
  import WeatherWidget from '$lib/components/WeatherWidget.svelte';
  ```
  und:
  ```svelte
  import ServiceStatus from '$lib/components/ServiceStatus.svelte';
  ```

  Beide Zeilen entfernen und durch eine neue Zeile ersetzen (nach den bestehenden Komponentenimporten):
  ```svelte
  import InfoPill from '$lib/components/InfoPill.svelte';
  ```

- [ ] **Step 2: `toggleClosures` auf Startpunkt-Koordinaten umstellen**

  Die aktuelle Funktion:
  ```svelte
  async function toggleClosures() {
    if (closures && showClosures) { showClosures = false; return; }
    showClosures = false;
    try {
      const [lat, lon] = mapCenter;
      closures = await overpassApi.getClosures(lat, lon) as FeatureCollection;
      showClosures = true;
    } catch { error = 'Sperrungsdaten nicht verfügbar'; }
  }
  ```

  Ersetzen durch:
  ```svelte
  async function toggleClosures() {
    if (closures && showClosures) { showClosures = false; return; }
    showClosures = false;
    try {
      const lat = selected?.start_point?.lat ?? mapCenter[0];
      const lon = selected?.start_point?.lon ?? mapCenter[1];
      closures = await overpassApi.getClosures(lat, lon) as FeatureCollection;
      showClosures = true;
    } catch { error = 'Sperrungsdaten nicht verfügbar'; }
  }
  ```

- [ ] **Step 3: `WeatherWidget` und `ServiceStatus` im Template ersetzen**

  Im Template-Bereich die Zeilen:
  ```svelte
  <!-- V3: Wetter-Widget -->
  <WeatherWidget lat={mapCenter[0]} lon={mapCenter[1]} />
  ```
  und:
  ```svelte
  <ServiceStatus />
  ```

  Beide entfernen und **eine** neue Zeile einfügen (an der Stelle von `<ServiceStatus />`):
  ```svelte
  <InfoPill
    startPoint={selected?.start_point}
    closuresCount={closures?.features?.length ?? 0}
    onShowClosures={toggleClosures}
  />
  ```

- [ ] **Step 4: Ungenutzte untracked Dateien entfernen**

  ```bash
  rm frontend/src/lib/components/WeatherWidget.svelte
  rm frontend/src/lib/components/ServiceStatus.svelte
  ```

- [ ] **Step 5: TypeScript prüfen**

  ```bash
  cd /Users/working_chris/GitHub/MarschPlan/frontend && npx tsc --noEmit 2>&1 | head -20
  ```
  Expected: keine neuen Fehler.

- [ ] **Step 6: Frontend bauen und starten**

  ```bash
  cd /Users/working_chris/GitHub/MarschPlan
  docker compose build frontend && docker compose up -d --no-deps frontend
  ```

  Prüfen:
  - Zentrierte Pill ist oben in der Mitte sichtbar
  - Klick auf Pill öffnet das Detailpanel
  - Service-Dots sind grün (außer weather_api + overpass_api: "unknown" = grau)
  - `curl -N http://localhost:8000/api/users/online` in Terminal → Count steigt beim Öffnen der App
  - Konvoi mit Startpunkt auswählen → Wetter erscheint in der Pill
  - Auf "Auf Karte anzeigen" klicken → Sperren werden geladen + auf Karte gezeigt
  - Nach Wetter-Laden → `curl -s http://localhost:8000/api/status | python3 -m json.tool` → `weather_api.status` ist nun `"ok"`

- [ ] **Step 7: Commit**

  ```bash
  git add frontend/src/routes/plan/+page.svelte
  git commit -m "feat(ui): wire InfoPill into plan page, replace WeatherWidget + ServiceStatus"
  ```
