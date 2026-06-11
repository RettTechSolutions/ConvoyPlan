<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import MapView from '$lib/components/MapView.svelte';
	import AppLogo from '$lib/components/AppLogo.svelte';
	import TrackingPwaHead from '$lib/components/TrackingPwaHead.svelte';
	import {
		trackApi, isTrackGate,
		type TrackPayload, type TrackGate, type TrackPosition, type VehiclePosition,
		type Waypoint,
	} from '$lib/api';
	import {
		STATUS_LABELS, STATUS_COLORS, STATUS_ICONS, HALT_LEVEL_LABELS, BREAKDOWN_LEVEL_LABELS,
		statusColor, statusLabel,
	} from '$lib/tracking/status';

	const slug = $derived($page.params.slug!);

	let data = $state<TrackPayload | null>(null);
	let gate = $state<TrackGate | null>(null);
	let error = $state('');
	let loading = $state(true);

	let pwInput = $state('');
	let pwBusy = $state(false);

	let activeTab = $state<'fahrzeuge' | 'zeitplan'>('fahrzeuge');
	let sidebarOpen = $state(false);
	let connected = $state(false);

	let livePositions = $state<Map<string, VehiclePosition>>(new Map());
	// Live vehicle status overrides received via WebSocket (vehicle_id → status).
	let liveStatuses = $state<Map<string, string>>(new Map());
	let ws: WebSocket | null = null;
	let mapView = $state<ReturnType<typeof MapView>>();

	// ── Driver mode (scope === 'driver'): pick a vehicle & send GPS/status ──
	const isSecure = typeof window !== 'undefined' && window.isSecureContext;
	let isDriver = $derived(data?.scope === 'driver');
	let myVehicleId = $state('');
	let transmitting = $state(false);
	let manualMode = $state(false);
	let geoWatcher: number | null = null;
	let driverError = $state('');
	let pendingStatus = $state<'technical_halt' | 'breakdown' | null>(null);
	let pendingNote = $state('');
	let wakeLock: WakeLockSentinel | null = null;
	const SESSION_KEY = $derived(`cp-track-driver-${slug}`);

	// Vehicles still free to pick (a vehicle already LIVE is "taken" — except mine).
	let availableVehicles = $derived(
		(data?.vehicles ?? []).filter((v) => v.id === myVehicleId || !livePositions.has(v.id))
	);
	let myStatus = $derived.by(() => {
		const v = (data?.vehicles ?? []).find((x) => x.id === myVehicleId);
		return v ? statusOf(v) : 'planned';
	});

	// vehicle id → label for live markers on the map
	let vehicleNames = $derived(
		new Map((data?.vehicles ?? []).map((v) => [v.id, v.callsign || v.name]))
	);
	// vehicle id → status color so the map markers reflect the current status.
	let vehicleColors = $derived(
		new Map((data?.vehicles ?? []).map((v) => [v.id, statusColor(statusOf(v))]))
	);

	// Only offer the schedule tab when at least one waypoint has a planned time.
	let hasSchedule = $derived((data?.waypoints ?? []).some((w) => w.planned_arrival));
	$effect(() => { if (!hasSchedule) activeTab = 'fahrzeuge'; });

	function statusOf(v: { id: string; vehicle_status: string | null }): string {
		return liveStatuses.get(v.id) ?? v.vehicle_status ?? 'planned';
	}

	function tokenStorageKey(s: string) { return `track_token_${s}`; }

	function loadStoredToken(): string | undefined {
		if (typeof sessionStorage === 'undefined') return undefined;
		return sessionStorage.getItem(tokenStorageKey(slug)) ?? undefined;
	}

	function storeToken(token: string) {
		try { sessionStorage.setItem(tokenStorageKey(slug), token); } catch { /* ignore */ }
	}

	function clearToken() {
		try { sessionStorage.removeItem(tokenStorageKey(slug)); } catch { /* ignore */ }
	}

	async function load() {
		loading = true;
		error = '';
		try {
			const token = loadStoredToken();
			const result = await trackApi.get(slug, token);
			if (isTrackGate(result)) {
				gate = result;
				data = null;
			} else {
				gate = null;
				data = result;
				const initial = new Map<string, VehiclePosition>();
				for (const p of result.positions) initial.set(p.vehicle_id, positionToVehicle(p));
				livePositions = initial;
				liveStatuses = new Map();
				connectWs(token);
				restoreDriverSession();
			}
		} catch (e) {
			error = (e as Error).message || 'Tracking-Link nicht erreichbar.';
		} finally {
			loading = false;
		}
	}

	async function submitPassword() {
		pwBusy = true;
		error = '';
		try {
			const { token } = await trackApi.auth(slug, pwInput);
			storeToken(token);
			pwInput = '';
			await load();
		} catch (e) {
			error = (e as Error).message || 'Falsches Passwort';
			clearToken();
		} finally {
			pwBusy = false;
		}
	}

	function positionToVehicle(p: TrackPosition): VehiclePosition {
		return {
			vehicle_id: p.vehicle_id,
			lat: p.lat, lon: p.lon,
			speed_kmh: p.speed_kmh, heading: p.heading,
			recorded_at: p.recorded_at,
		};
	}

	function connectWs(token?: string) {
		if (typeof window === 'undefined') return;
		const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
		const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
		ws = new WebSocket(`${proto}//${window.location.host}/api/ws/track/${slug}${tokenParam}`);
		ws.onopen = () => { connected = true; };
		ws.onmessage = (ev) => {
			try {
				const msg = JSON.parse(ev.data);
				if (msg.type === 'status_update') {
					if (typeof msg.vehicle_id === 'string' && typeof msg.vehicle_status === 'string') {
						const next = new Map(liveStatuses);
						next.set(msg.vehicle_id, msg.vehicle_status);
						liveStatuses = next;
					}
					return;
				}
				if (msg.type === 'position_cleared') {
					if (typeof msg.vehicle_id === 'string') {
						const next = new Map(livePositions);
						next.delete(msg.vehicle_id);
						livePositions = next;
					}
					return;
				}
				if (typeof msg.vehicle_id !== 'string' || typeof msg.lat !== 'number') return;
				const next = new Map(livePositions);
				next.set(msg.vehicle_id, {
					vehicle_id: msg.vehicle_id,
					lat: msg.lat, lon: msg.lon,
					speed_kmh: msg.speed_kmh ?? null,
					heading: msg.heading ?? null,
					recorded_at: new Date().toISOString(),
				});
				livePositions = next;
			} catch { /* ignore */ }
		};
		ws.onclose = () => { connected = false; };
		ws.onerror = () => { connected = false; /* silent — UI keeps last snapshot */ };
	}

	function fmtTime(iso: string | null) {
		if (!iso) return '–';
		return new Date(iso).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
	}

	// ── Driver actions ──────────────────────────────────────────────────────
	function wsReady(): boolean {
		return ws?.readyState === WebSocket.OPEN;
	}

	function sendDriverPosition(lat: number, lon: number, speedKmh?: number, heading?: number) {
		if (!wsReady() || !myVehicleId) return;
		ws!.send(JSON.stringify({ vehicle_id: myVehicleId, lat, lon, speed_kmh: speedKmh, heading }));
		// Optimistic local marker so the driver sees themselves immediately.
		const next = new Map(livePositions);
		next.set(myVehicleId, { vehicle_id: myVehicleId, lat, lon, speed_kmh: speedKmh ?? null, heading: heading ?? null, recorded_at: new Date().toISOString() });
		livePositions = next;
	}

	function startTransmitting() {
		if (!myVehicleId) { driverError = 'Bitte zuerst ein Fahrzeug auswählen'; return; }
		driverError = '';
		try { sessionStorage.setItem(SESSION_KEY, myVehicleId); } catch { /* ignore */ }
		requestWakeLock();
		if (!isSecure) { manualMode = true; transmitting = true; return; }
		transmitting = true;
		manualMode = false;
		if (geoWatcher !== null) { navigator.geolocation.clearWatch(geoWatcher); geoWatcher = null; }
		geoWatcher = navigator.geolocation.watchPosition(
			(pos) => {
				if (!transmitting) return;
				driverError = '';
				const { latitude, longitude, speed, heading } = pos.coords;
				sendDriverPosition(latitude, longitude, speed ? speed * 3.6 : undefined, heading ?? undefined);
			},
			(e) => {
				if (e.code === e.PERMISSION_DENIED) { manualMode = true; driverError = ''; }
				else driverError = `GPS-Fehler: ${e.message}`;
			},
			{ enableHighAccuracy: true, maximumAge: 5000 }
		);
	}

	function stopTransmitting() {
		if (geoWatcher !== null) { navigator.geolocation.clearWatch(geoWatcher); geoWatcher = null; }
		transmitting = false;
		manualMode = false;
		releaseWakeLock();
		try { sessionStorage.removeItem(SESSION_KEY); } catch { /* ignore */ }
	}

	function handleMapTap(lat: number, lon: number) {
		if (!transmitting || !manualMode || !myVehicleId) return;
		sendDriverPosition(lat, lon);
	}

	function sendDriverStatus(status: string, level: string | null = null, note: string | null = null) {
		if (!wsReady() || !myVehicleId) { driverError = 'Keine Verbindung – Status nicht gesendet'; return; }
		ws!.send(JSON.stringify({ type: 'status', vehicle_id: myVehicleId, vehicle_status: status, status_level: level, status_note: note }));
		// Optimistic local update.
		const next = new Map(liveStatuses);
		next.set(myVehicleId, status);
		liveStatuses = next;
		pendingStatus = null;
		pendingNote = '';
	}

	function chooseStatus(status: string) {
		if (!myVehicleId) { driverError = 'Bitte zuerst ein Fahrzeug auswählen'; return; }
		if (status === 'technical_halt' || status === 'breakdown') {
			pendingStatus = pendingStatus === status ? null : status;
			pendingNote = '';
			return;
		}
		sendDriverStatus(status);
	}

	function confirmPending(level: string) {
		if (pendingStatus) sendDriverStatus(pendingStatus, level, pendingNote.trim() || null);
	}

	async function requestWakeLock() {
		try {
			if ('wakeLock' in navigator) {
				wakeLock = await navigator.wakeLock.request('screen');
				wakeLock.addEventListener('release', () => { wakeLock = null; });
			}
		} catch { /* non-critical */ }
	}
	function releaseWakeLock() { wakeLock?.release().catch(() => {}); wakeLock = null; }

	// Resume a previously picked vehicle after a reload (driver links only).
	function restoreDriverSession() {
		if (!isDriver) return;
		try {
			const saved = sessionStorage.getItem(SESSION_KEY);
			if (saved && (data?.vehicles ?? []).some((v) => v.id === saved)) {
				myVehicleId = saved;
				startTransmitting();
			}
		} catch { /* ignore */ }
	}

	onMount(load);
	onDestroy(() => {
		if (geoWatcher !== null) navigator.geolocation.clearWatch(geoWatcher);
		releaseWakeLock();
		ws?.close();
	});
</script>

<TrackingPwaHead />

<div class="app">
	<!-- Mobile top bar -->
	<div class="topbar">
		<button class="hamburger" onclick={() => (sidebarOpen = !sidebarOpen)} aria-label="Menü">☰</button>
		<span class="topbar-name">{data?.name ?? gate?.convoy_name ?? 'Tracking'}</span>
		<div class="ws-dot" class:connected title={connected ? 'Verbunden' : 'Nicht verbunden'}></div>
	</div>

	<!-- Sidebar backdrop (mobile) -->
	{#if sidebarOpen}
		<button class="sidebar-backdrop" onclick={() => (sidebarOpen = false)} aria-label="Menü schließen"></button>
	{/if}

	<!-- Sidebar -->
	<aside class="sidebar" class:open={sidebarOpen}>
		<div class="sidebar-header">
			<div class="logo-wrap">
				<AppLogo width={null} />
				<div class="convoy-name">{data?.name ?? gate?.convoy_name ?? 'Laden…'}</div>
				{#if data?.organization}<div class="org-name">{data.organization}</div>{/if}
			</div>
			{#if data}
				<div class="ws-indicator" class:connected title={connected ? 'Verbunden' : 'Nicht verbunden'}>
					<span class="ws-dot" class:connected></span>
					<span class="ws-label">{connected ? 'Live' : 'Getrennt'}</span>
				</div>
			{/if}
		</div>

		{#if loading}
			<div class="tab-content"><p class="hint">Lade…</p></div>
		{:else if gate}
			<div class="gate">
				<p class="hint">Dieser Tracking-Link ist passwortgeschützt.</p>
				<form onsubmit={(e) => { e.preventDefault(); submitPassword(); }}>
					<input
						type="password"
						placeholder="Passwort"
						bind:value={pwInput}
						autocomplete="current-password"
						required
					/>
					<button type="submit" class="btn-primary" disabled={pwBusy || !pwInput}>
						{pwBusy ? 'Prüfe…' : 'Öffnen'}
					</button>
				</form>
				{#if error}<p class="error-text">{error}</p>{/if}
			</div>
		{:else if data}
			{#if data.start_time}
				<div class="info-block">
					<span class="info-label">Start</span>
					<span class="info-value">{new Date(data.start_time).toLocaleString('de-DE')}</span>
				</div>
			{/if}

			{#if isDriver}
				<!-- Driver link: pick a vehicle and send position / status without login -->
				<div class="driver-block">
					<div class="info-label">Meine Position (Fahrer)</div>
					{#if driverError}<p class="error-text">{driverError}</p>{/if}
					<select bind:value={myVehicleId} disabled={transmitting}>
						<option value="">Fahrzeug wählen…</option>
						{#each availableVehicles as v}
							<option value={v.id}>{v.name}{v.callsign ? ` (${v.callsign})` : ''}</option>
						{/each}
					</select>
					{#if !transmitting}
						{#if !isSecure}<p class="hint">GPS benötigt HTTPS – Position kann per Karten-Tippen gesetzt werden.</p>{/if}
						<button class="btn-primary" onclick={startTransmitting} disabled={!myVehicleId}>
							{isSecure ? '📡 GPS senden' : '📍 Manuell setzen'}
						</button>
					{:else}
						<p class="hint hint-active">{manualMode ? 'Tippe auf die Karte, um deine Position zu setzen' : 'GPS aktiv – Position wird übertragen'}</p>
						<button class="btn-stop" onclick={stopTransmitting}>⏹ Senden stoppen</button>
					{/if}

					{#if myVehicleId}
						<div class="status-grid">
							{#each ['planned', 'en_route', 'arrived'] as st}
								<button class="status-btn" class:active={myStatus === st} style="--c:{statusColor(st)}" onclick={() => chooseStatus(st)}>
									<span class="sb-icon">{STATUS_ICONS[st]}</span>{STATUS_LABELS[st]}
								</button>
							{/each}
							<button class="status-btn wide" class:active={myStatus === 'technical_halt'} class:expanded={pendingStatus === 'technical_halt'} style="--c:{statusColor('technical_halt')}" onclick={() => chooseStatus('technical_halt')}>
								<span class="sb-icon">{STATUS_ICONS.technical_halt}</span>Technischen Halt anfordern
							</button>
							{#if pendingStatus === 'technical_halt'}
								<div class="sub-panel">
									<div class="sub-label">Dringlichkeit wählen</div>
									{#each Object.entries(HALT_LEVEL_LABELS) as [val, label]}
										<button class="sub-btn lvl-{val}" onclick={() => confirmPending(val)}>{label}</button>
									{/each}
									<input class="note-input" placeholder="Grund (optional)" bind:value={pendingNote} maxlength="200" />
								</div>
							{/if}
							<button class="status-btn wide" class:active={myStatus === 'breakdown'} class:expanded={pendingStatus === 'breakdown'} style="--c:{statusColor('breakdown')}" onclick={() => chooseStatus('breakdown')}>
								<span class="sb-icon">{STATUS_ICONS.breakdown}</span>Ausfall / Technische Störung
							</button>
							{#if pendingStatus === 'breakdown'}
								<div class="sub-panel">
									<div class="sub-label">Schweregrad wählen</div>
									{#each Object.entries(BREAKDOWN_LEVEL_LABELS) as [val, label]}
										<button class="sub-btn break-{val}" onclick={() => confirmPending(val)}>{label}</button>
									{/each}
									<input class="note-input" placeholder="Beschreibung (optional)" bind:value={pendingNote} maxlength="200" />
								</div>
							{/if}
						</div>
					{/if}
				</div>
			{/if}

			<!-- Tabs -->
			<div class="tabs">
				<button class="tab" class:active={activeTab === 'fahrzeuge'} onclick={() => (activeTab = 'fahrzeuge')}>Fahrzeuge</button>
				{#if hasSchedule}
					<button class="tab" class:active={activeTab === 'zeitplan'} onclick={() => (activeTab = 'zeitplan')}>Zeitplan</button>
				{/if}
			</div>

			<div class="tab-content">
				{#if activeTab === 'fahrzeuge'}
					<div class="section">
						{#each data.vehicles as v}
							<div class="vehicle-row">
								<div class="veh-left">
									<span class="status-dot" style="background:{STATUS_COLORS[statusOf(v)] ?? '#95a5a6'}"></span>
									<span class="vname">{v.name}</span>
									{#if v.callsign}<span class="tag">{v.callsign}</span>{/if}
									{#if v.sonderfunktion}<span class="tag">{v.sonderfunktion}</span>{/if}
									{#if livePositions.has(v.id)}<span class="live-badge">LIVE</span>{/if}
								</div>
								<span class="status-label" style="color:{STATUS_COLORS[statusOf(v)] ?? '#95a5a6'}">
									{STATUS_LABELS[statusOf(v)] ?? statusOf(v)}
								</span>
							</div>
						{/each}
						{#if data.vehicles.length === 0}
							<p class="hint">Keine Fahrzeuge im Verband</p>
						{/if}
					</div>
				{:else if activeTab === 'zeitplan'}
					<div class="section">
						<table class="schedule-table">
							<thead><tr><th>Wegpunkt</th><th>Ankunft</th><th>Abfahrt</th></tr></thead>
							<tbody>
								{#each data.waypoints as wp}
									<tr>
										<td>{wp.name}</td>
										<td>{fmtTime(wp.planned_arrival)}</td>
										<td>{fmtTime(wp.planned_departure)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>
		{:else if error}
			<div class="tab-content"><p class="error-text">{error}</p></div>
		{/if}
	</aside>

	<!-- Map -->
	<main class="map-area" class:cursor-crosshair={isDriver && manualMode && transmitting}>
		{#if data}
			<div class="map-controls">
				{#if data.geojson}
					<button class="map-ctrl-btn" onclick={() => mapView?.showRoute()} title="Gesamte Route anzeigen">
						🗺️ Route
					</button>
				{/if}
			</div>
			{#if isDriver && manualMode && transmitting}
				<div class="map-hint-bar">Tippe auf die Karte, um deine Position zu senden</div>
			{/if}
			<MapView
				bind:this={mapView}
				waypoints={data.waypoints as unknown as Waypoint[]}
				routeGeojson={data.geojson}
				livePositions={livePositions}
				vehicleNames={vehicleNames}
				vehicleColors={vehicleColors}
				clickEnabled={isDriver && manualMode && transmitting}
				onMapClick={handleMapTap}
			/>
		{/if}
	</main>
</div>

<style>
	:global(body) { margin: 0; font-family: system-ui, sans-serif; }
	.app { display: flex; height: 100vh; height: 100dvh; overflow: hidden; }

	/* Sidebar */
	.sidebar { width: 320px; min-width: 280px; background: var(--sidebar-bg); color: var(--text-1); display: flex; flex-direction: column; overflow: hidden; }
	.sidebar-header { display: flex; justify-content: space-between; align-items: flex-start; padding: 1rem; border-bottom: 1px solid var(--border); background: var(--sidebar-bg); }
	.logo-wrap { flex: 1; min-width: 0; }
	.convoy-name { font-size: var(--text-xs); color: var(--text-2); margin-top: .25rem; }
	.org-name { font-size: var(--text-xs); color: var(--text-muted); margin-top: .1rem; }

	/* WS indicator */
	.ws-indicator { display: flex; align-items: center; gap: .35rem; font-size: var(--text-xs); color: var(--text-muted); flex-shrink: 0; }
	.ws-dot { width: 8px; height: 8px; border-radius: 50%; background: #e74c3c; flex-shrink: 0; }
	.ws-dot.connected { background: #27ae60; animation: pulse 2s infinite; }
	.ws-label { white-space: nowrap; }

	/* Info block (start time) */
	.info-block { padding: .75rem 1rem; border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: .15rem; flex-shrink: 0; }
	.info-label { font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); }
	.info-value { font-size: var(--text-sm); color: var(--text-2); }

	/* Gate (password) */
	.gate { padding: .75rem 1rem; }
	.gate form { display: flex; flex-direction: column; gap: .5rem; margin-top: .75rem; }
	.gate input { padding: .55rem .7rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
	.error-text { color: var(--color-primary); font-size: var(--text-sm); margin-top: .5rem; }

	.btn-primary { width: 100%; padding: .5rem 1rem; background: var(--color-primary); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
	.btn-primary:disabled { opacity: .5; cursor: not-allowed; }
	.btn-primary:hover:not(:disabled) { background: var(--color-primary-hover); }
	.btn-stop { width: 100%; padding: .5rem 1rem; background: rgba(226,61,40,.3); border: 1px solid var(--color-primary); color: var(--text-1); border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }

	/* Driver block (driver-scope share links) */
	.driver-block { padding: .75rem 1rem; border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: .5rem; flex-shrink: 0; }
	.driver-block select { width: 100%; padding: .5rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
	.driver-block select:disabled { opacity: .6; }
	.hint.hint-active { color: #f1c40f; font-style: normal; }
	.status-grid { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .25rem; }
	.status-btn { flex: 1 1 calc(33% - .5rem); display: flex; flex-direction: column; align-items: center; gap: .25rem; padding: .55rem .4rem; background: var(--surface-2); color: var(--text-1); border: 2px solid var(--border); border-radius: 8px; cursor: pointer; font-size: var(--text-xs); font-weight: 600; text-align: center; }
	.status-btn.wide { flex-basis: 100%; flex-direction: row; justify-content: center; font-size: var(--text-sm); }
	.status-btn .sb-icon { color: var(--c); font-size: 1.05rem; }
	.status-btn:hover { border-color: var(--c); }
	.status-btn.active { border-color: var(--c); box-shadow: inset 0 0 0 1px var(--c); }
	.sub-panel { flex-basis: 100%; display: flex; flex-direction: column; gap: .4rem; padding: .6rem; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; }
	.sub-label { font-size: var(--text-xs); color: var(--text-muted); }
	.sub-btn { padding: .5rem; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: var(--text-sm); color: #1a1a1a; }
	.sub-btn.lvl-standard { background: #f7dc6f; }
	.sub-btn.lvl-dringend { background: #f1c40f; }
	.sub-btn.lvl-sehr_dringend { background: #e67e22; color: #fff; }
	.sub-btn.break-limited { background: #e67e22; color: #fff; }
	.sub-btn.break-total { background: #E23D28; color: #fff; }
	.note-input { padding: .45rem .5rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
	.map-hint-bar { position: absolute; top: 1rem; left: 50%; transform: translateX(-50%); z-index: 10; background: rgba(15,27,36,.9); color: white; padding: .5rem 1.2rem; border-radius: 20px; font-size: var(--text-sm); pointer-events: none; white-space: nowrap; }

	.hint { font-size: var(--text-xs); color: var(--text-muted); font-style: italic; margin: 0; line-height: 1.4; }

	/* Tabs */
	.tabs { display: flex; overflow-x: auto; scrollbar-width: none; border-bottom: 1px solid var(--border); padding: .25rem .5rem; gap: .25rem; flex-shrink: 0; }
	.tabs::-webkit-scrollbar { display: none; }
	.tab { flex: 0 0 auto; padding: .5rem .75rem; background: none; border: none; color: var(--text-2); font-size: var(--text-sm); cursor: pointer; white-space: nowrap; border-radius: 4px; }
	.tab.active { color: var(--text-1); background: var(--surface-2); font-weight: 600; }

	/* Tab content */
	.tab-content { flex: 1; overflow-y: auto; padding: .75rem 1rem; }
	.section { margin-bottom: .75rem; }

	/* Vehicle rows */
	.vehicle-row { display: flex; align-items: center; justify-content: space-between; padding: .35rem 0; border-bottom: 1px solid var(--border); gap: .4rem; }
	.veh-left { display: flex; align-items: center; gap: .3rem; flex: 1; min-width: 0; }
	.status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
	.vname { font-size: var(--text-sm); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.tag { display: inline-block; padding: .05rem .3rem; background: var(--surface-2); border-radius: 3px; font-size: var(--text-xs); flex-shrink: 0; color: var(--text-2); }
	.live-badge { background: #27ae60; color: white; border-radius: 3px; padding: .05rem .3rem; font-size: var(--text-xs); font-weight: 700; flex-shrink: 0; animation: pulse 1.5s infinite; }
	.status-label { font-size: var(--text-xs); font-weight: 600; white-space: nowrap; flex-shrink: 0; }

	/* Schedule table */
	.schedule-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
	.schedule-table th, .schedule-table td { padding: .5rem; text-align: left; border-bottom: 1px solid var(--border); }
	.schedule-table th { color: var(--text-muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .04em; }

	/* Map */
	.map-area { flex: 1; position: relative; }
	.map-area.cursor-crosshair :global(.maplibregl-canvas) { cursor: crosshair; }

	/* Map control buttons (Route) */
	.map-controls { position: absolute; right: .75rem; bottom: calc(.75rem + env(safe-area-inset-bottom, 0px)); z-index: 10; display: flex; flex-direction: column; align-items: flex-end; gap: .5rem; max-width: calc(100% - 1.5rem); }
	.map-ctrl-btn { display: flex; align-items: center; gap: .4rem; background: var(--color-primary); color: white; border: none; padding: .55rem .9rem; border-radius: 22px; font-size: var(--text-sm); font-weight: 600; cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,.35); white-space: nowrap; }
	.map-ctrl-btn:hover { background: var(--color-primary-hover); }

	/* Mobile topbar */
	.topbar { display: none; }
	.sidebar-backdrop { display: none; }

	@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .4; } }

	@media (max-width: 700px) {
		.topbar { display: flex; align-items: center; gap: .75rem; padding: .75rem 1rem; background: var(--sidebar-bg); color: var(--text-1); border-bottom: 1px solid var(--border); position: fixed; top: 0; left: 0; right: 0; z-index: 50; height: 48px; box-sizing: border-box; }
		.hamburger { background: none; border: none; color: var(--text-1); font-size: 1.3rem; cursor: pointer; padding: 0; }
		.topbar-name { flex: 1; font-size: var(--text-sm); font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
		.topbar .ws-dot { margin-left: auto; }

		.app { flex-direction: column; padding-top: 48px; }
		.sidebar { position: fixed; top: 48px; left: 0; bottom: 0; z-index: 40; transform: translateX(-100%); transition: transform .25s ease; width: 300px; overflow-y: hidden; }
		.sidebar.open { transform: translateX(0); box-shadow: 4px 0 24px rgba(0,0,0,.5); }
		.sidebar-backdrop { display: block; position: fixed; inset: 0; top: 48px; background: rgba(0,0,0,.4); z-index: 39; border: none; cursor: pointer; }
		.map-area { flex: 1; }
	}
</style>
