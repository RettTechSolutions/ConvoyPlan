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
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  let sse: EventSource | null = null;
  let reconnectDelay = 5_000;          // starts at 5 s
  const MAX_RECONNECT_DELAY = 60_000;  // caps at 60 s
  let destroyed = false;

  async function fetchStatus() {
    try {
      status = await statusApi.get();
    } catch { /* ignore */ }
  }

  async function connectSSE() {
    if (sse) { sse.close(); sse = null; }
    // onlineStream is async (fetches a short-lived stream ticket first).
    const es = await usersApi.onlineStream();
    if (destroyed) { es.close(); return; } // component went away while awaiting
    sse = es;
    es.onmessage = (e) => {
      try { onlineCount = JSON.parse(e.data).count ?? 0; } catch { /* ignore */ }
      reconnectDelay = 5_000; // reset backoff on successful message
    };
    es.onerror = () => {
      es.close();
      if (sse === es) sse = null;
      if (destroyed) return;
      reconnectTimer = setTimeout(connectSSE, reconnectDelay);
      // exponential backoff: 5 s → 10 s → 20 s → 40 s → 60 s (capped)
      reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
    };
  }

  $effect(() => {
    if (!startPoint?.lat || !startPoint?.lon) {
      weather = null;
      return;
    }
    const controller = new AbortController();
    weatherLoading = true;
    weatherApi.get(startPoint.lat, startPoint.lon)
      .then(w => { if (!controller.signal.aborted) weather = w; })
      .catch(() => { if (!controller.signal.aborted) weather = null; })
      .finally(() => { if (!controller.signal.aborted) weatherLoading = false; });
    return () => controller.abort();
  });

  onMount(() => {
    fetchStatus();
    pollInterval = setInterval(fetchStatus, 30_000);
    connectSSE();
  });

  onDestroy(() => {
    destroyed = true;
    clearInterval(pollInterval);
    clearTimeout(reconnectTimer);
    sse?.close();
  });

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
</script>

<div class="pill-wrap">
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
      <span class="dot {svcColor(status?.overpass_api?.status)}" title="Sperren-API (Overpass)"></span>
      <span class="dot {svcColor(status?.autobahn_api?.status)}" title="Autobahn-API"></span>
    </span>

    <span class="pill-sep">·</span>
    <span class="pill-users">👥 {onlineCount}</span>

    {#if closuresCount > 0}
      <span class="pill-sep">·</span>
      <span class="pill-closures">⚠ {closuresCount} Sperren</span>
    {/if}
  </button>

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
          <div class="svc-row">
            <span class="dot {svcColor(status?.autobahn_api?.status)}"></span>
            <span class="svc-name">Autobahn (bund.dev)</span>
            <span class="svc-val {svcColor(status?.autobahn_api?.status)}">
              {status?.autobahn_api?.status === 'ok'
                ? `${status.autobahn_api.latency_ms} ms`
                : (status?.autobahn_api?.status ?? '–')}
            </span>
          </div>
        </div>

        <div class="right-col">
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
    left: 1rem;
    z-index: 150;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    pointer-events: none;
  }
  .pill-wrap > * {
    pointer-events: auto;
  }

  .pill {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 16px;
    background: rgba(15, 27, 36, 0.92);
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
  .pill:hover { background: rgba(15, 27, 36, .98); }

  .pill-ico { font-size: 14px; }
  .pill-temp { font-weight: 700; font-size: 13px; }
  .pill-sep { color: rgba(255, 255, 255, .3); }
  .pill-dots { display: flex; align-items: center; gap: 4px; }
  .pill-users { font-size: 11px; }
  .pill-closures {
    background: var(--color-primary-hover);
    border-radius: 10px;
    padding: 2px 8px;
    font-size: 9px;
    font-weight: 600;
  }

  .dot {
    display: inline-block;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .dot.ok { background: #27ae60; }
  .dot.warn { background: #f39c12; }
  .dot.err { background: var(--color-primary); }
  .dot.unknown { background: #6b7177; }

  .panel {
    margin-top: 6px;
    background: rgba(15, 27, 36, 0.97);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, .15);
    border-radius: 12px;
    padding: 14px 16px;
    color: white;
    font-size: 11px;
    box-shadow: 0 8px 30px rgba(0, 0, 0, .5);
    width: min(440px, calc(100vw - 2rem));
    box-sizing: border-box;
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

  .svc-list { display: flex; flex-direction: column; gap: 5px; }
  .svc-row { display: flex; align-items: center; gap: 6px; }
  .svc-name { flex: 1; color: rgba(255,255,255,.65); }
  .svc-val { font-weight: 600; font-size: 10px; }
  .svc-val.ok { color: #2ecc71; }
  .svc-val.warn { color: #f39c12; }
  .svc-val.err { color: var(--color-primary); }
  .svc-val.unknown { color: #6b7177; }

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

  .users-block {
    background: rgba(255,255,255,.05);
    border-radius: 6px;
    padding: 8px;
  }
  .users-count { display: flex; align-items: center; gap: 6px; }
  .users-ico { font-size: 18px; }
  .users-num { font-weight: 700; font-size: 20px; }
  .users-label { color: rgba(255,255,255,.45); font-size: 9px; }

  .closures-block {
    margin-top: 12px;
    border-top: 1px solid rgba(255,255,255,.08);
    padding-top: 10px;
  }
  .closures-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
  .closures-badge {
    background: var(--color-primary-hover); border-radius: 10px;
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

  @media (max-width: 768px) {
    .pill-wrap {
      top: 10px;
      left: .75rem;
    }
    .pill {
      font-size: 12px;
      padding: 8px 14px;
    }
    .pill-temp { font-size: 14px; }
    .panel {
      width: 100%;
      font-size: 12px;
      padding: 12px 14px;
    }
    .panel-grid {
      grid-template-columns: 1fr;
      gap: 12px 0;
    }
    .svc-name { font-size: 12px; }
    .svc-val { font-size: 11px; }
    .col-label { font-size: 10px; }
    .forecast { flex-wrap: wrap; }
    .fc-hour { font-size: 10px; }
    .fc-ico { font-size: 12px; }
    .fc-temp, .fc-precip { font-size: 11px; }
  }
</style>
