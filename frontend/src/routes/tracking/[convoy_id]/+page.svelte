<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import MapView from '$lib/components/MapView.svelte';
	import AppLogo from '$lib/components/AppLogo.svelte';
	import { convoysApi, trackingApi, type Convoy, type VehiclePosition, type RouteResult } from '$lib/api';
	import { livePositions, vehicleStatuses, connectTracking, disconnectTracking, sendPosition, trackingActive } from '$lib/stores/tracking';

	const convoyId = $page.params.convoy_id;

	let convoy = $state<Convoy | null>(null);
	let routeGeojson = $state<RouteResult['geojson']>(null);
	let myVehicleId = $state('');
	let transmitting = $state(false);
	let manualMode = $state(false);
	let activeTab = $state<'fahrzeuge' | 'zeitplan'>('fahrzeuge');
	let sidebarOpen = $state(false);
	let geoWatcher: number | null = null;
	let mapCenter = $state<[number, number]>([10.0, 51.5]);
	let error = $state('');

	const isSecure = typeof window !== 'undefined' && window.isSecureContext;

	const STATUS_LABELS: Record<string, string> = { planned: 'Geplant', en_route: 'Unterwegs', arrived: 'Angekommen', delayed: 'Verspätung' };
	const STATUS_COLORS: Record<string, string> = { planned: '#95a5a6', en_route: '#3498db', arrived: '#27ae60', delayed: '#E23D28' };

	onMount(async () => {
		try {
			[convoy] = await Promise.all([
				convoysApi.get(convoyId),
				convoysApi.getRoute(convoyId).then(r => { routeGeojson = r?.geojson ?? null; }),
				trackingApi.getPositions(convoyId).then(positions => {
					livePositions.set(new Map(positions.map(p => [p.vehicle_id, p])));
				}),
			]);
			connectTracking(convoyId);
		} catch {
			error = 'Marschverband konnte nicht geladen werden';
		}
	});

	onDestroy(() => {
		disconnectTracking();
		stopTransmitting();
	});

	function startTransmitting() {
		if (!myVehicleId) { error = 'Bitte zuerst ein Fahrzeug auswählen'; return; }
		error = '';
		if (!isSecure) {
			manualMode = true;
			transmitting = true;
			return;
		}
		transmitting = true;
		manualMode = false;
		geoWatcher = navigator.geolocation.watchPosition(
			(pos) => {
				error = '';
				const { latitude: lat, longitude: lon, speed, heading } = pos.coords;
				sendPosition(convoyId, myVehicleId, lat, lon, speed ? speed * 3.6 : undefined, heading ?? undefined);
			},
			(e) => {
				if (e.code === e.PERMISSION_DENIED) {
					manualMode = true;
					error = '';
				} else {
					error = `GPS-Fehler: ${e.message}`;
				}
			},
			{ enableHighAccuracy: true, maximumAge: 5000 }
		);
	}

	function stopTransmitting() {
		if (geoWatcher !== null) { navigator.geolocation.clearWatch(geoWatcher); geoWatcher = null; }
		transmitting = false;
		manualMode = false;
	}

	function handleMapTap(lat: number, lon: number) {
		if (!transmitting || !manualMode || !myVehicleId) return;
		sendPosition(convoyId, myVehicleId, lat, lon, undefined, undefined);
	}

	async function setStatus(vehicleId: string, status: string) {
		try {
			await trackingApi.updateVehicleStatus(convoyId, vehicleId, status);
		} catch { error = 'Status konnte nicht aktualisiert werden'; }
	}

	function formatTime(iso: string | null) {
		if (!iso) return '-';
		return new Date(iso).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
	}

	$derived: activeTab = convoy?.waypoints.some(w => w.planned_arrival) ? activeTab : 'fahrzeuge';
</script>

<div class="app">
	<!-- Mobile top bar -->
	<div class="topbar">
		<button class="hamburger" onclick={() => (sidebarOpen = !sidebarOpen)} aria-label="Menü">☰</button>
		<span class="topbar-name">{convoy?.name ?? 'Tracking'}</span>
		<div class="ws-dot" class:connected={$trackingActive} title={$trackingActive ? 'Verbunden' : 'Nicht verbunden'}></div>
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
				<div class="convoy-name">{convoy?.name ?? 'Laden…'}</div>
				{#if convoy?.organization}<div class="org-name">{convoy.organization}</div>{/if}
			</div>
			<div class="ws-indicator" class:connected={$trackingActive} title={$trackingActive ? 'Verbunden' : 'Nicht verbunden'}>
				<span class="ws-dot" class:connected={$trackingActive}></span>
				<span class="ws-label">{$trackingActive ? 'Live' : 'Getrennt'}</span>
			</div>
		</div>

		{#if error}
			<div class="error-bar">
				<span>{error}</span>
				<button onclick={() => (error = '')}>✕</button>
			</div>
		{/if}

		<!-- Meine Position -->
		<div class="position-block">
			<div class="position-label">Meine Position</div>
			<select bind:value={myVehicleId} disabled={transmitting}>
				<option value="">Fahrzeug wählen…</option>
				{#each (convoy?.convoy_vehicles ?? []) as cv}
					<option value={cv.vehicle.id}>{cv.vehicle.name}{cv.vehicle.callsign ? ` (${cv.vehicle.callsign})` : ''}</option>
				{/each}
			</select>
			{#if !transmitting}
				{#if !isSecure}
					<p class="hint">GPS benötigt HTTPS. Manuelle Positionierung via Karten-Tippen verfügbar.</p>
				{/if}
				<button class="btn-primary" onclick={startTransmitting} disabled={!myVehicleId}>
					{isSecure ? '📡 GPS senden' : '📍 Manuell setzen'}
				</button>
			{:else}
				{#if manualMode}
					<p class="hint hint-active">Tippe auf die Karte um deine Position zu setzen</p>
				{:else}
					<p class="hint hint-active">GPS aktiv – Position wird übertragen</p>
				{/if}
				<button class="btn-stop" onclick={stopTransmitting}>⏹ Senden stoppen</button>
			{/if}
		</div>

		<!-- Tabs -->
		<div class="tabs">
			<button class="tab" class:active={activeTab === 'fahrzeuge'} onclick={() => (activeTab = 'fahrzeuge')}>Fahrzeuge</button>
			{#if convoy?.waypoints.some(w => w.planned_arrival)}
				<button class="tab" class:active={activeTab === 'zeitplan'} onclick={() => (activeTab = 'zeitplan')}>Zeitplan</button>
			{/if}
		</div>

		<div class="tab-content">
			{#if activeTab === 'fahrzeuge'}
				<div class="section">
					{#each (convoy?.convoy_vehicles ?? []) as cv}
						<div class="vehicle-row">
							<div class="veh-left">
								<span class="status-dot" style="background:{STATUS_COLORS[$vehicleStatuses.get(cv.vehicle.id) ?? cv.vehicle_status] ?? '#95a5a6'}"></span>
								<span class="vname">{cv.vehicle.name}</span>
								{#if cv.vehicle.callsign}<span class="tag">{cv.vehicle.callsign}</span>{/if}
								{#if $livePositions.has(cv.vehicle.id)}<span class="live-badge">LIVE</span>{/if}
							</div>
							<select
								class="status-select"
								value={$vehicleStatuses.get(cv.vehicle.id) ?? cv.vehicle_status}
								onchange={(e) => setStatus(cv.vehicle.id, (e.target as HTMLSelectElement).value)}
								style="border-color:{STATUS_COLORS[$vehicleStatuses.get(cv.vehicle.id) ?? cv.vehicle_status] ?? '#95a5a6'}"
							>
								{#each Object.entries(STATUS_LABELS) as [val, label]}
									<option value={val}>{label}</option>
								{/each}
							</select>
						</div>
					{/each}
					{#if (convoy?.convoy_vehicles ?? []).length === 0}
						<p class="hint">Keine Fahrzeuge im Verband</p>
					{/if}
				</div>

			{:else if activeTab === 'zeitplan'}
				<div class="section">
					<table class="schedule-table">
						<thead><tr><th>Wegpunkt</th><th>Ankunft</th><th>Abfahrt</th></tr></thead>
						<tbody>
							{#each (convoy?.waypoints ?? []) as wp}
								<tr>
									<td>{wp.name}</td>
									<td>{formatTime(wp.planned_arrival)}</td>
									<td>{formatTime(wp.planned_departure)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>
	</aside>

	<!-- Map -->
	<main class="map-area" class:cursor-crosshair={manualMode && transmitting}>
		{#if manualMode && transmitting}
			<div class="map-hint-bar">Tippe auf die Karte um Position zu senden</div>
		{/if}
		<MapView
			startPoint={convoy?.start_point}
			endPoint={convoy?.end_point}
			waypoints={convoy?.waypoints ?? []}
			routeGeojson={routeGeojson}
			livePositions={$livePositions}
			clickEnabled={manualMode && transmitting}
			onMapClick={handleMapTap}
			onMapMove={(lat, lon) => (mapCenter = [lat, lon])}
		/>
	</main>
</div>

<style>
	:global(body) { margin: 0; font-family: system-ui, sans-serif; }
	.app { display: flex; height: 100vh; overflow: hidden; }

	/* Sidebar */
	.sidebar { width: 320px; min-width: 280px; background: var(--sidebar-bg); color: var(--text-1); display: flex; flex-direction: column; overflow: hidden; }
	.sidebar-header { display: flex; justify-content: space-between; align-items: flex-start; padding: 1rem; border-bottom: 1px solid var(--border); background: var(--sidebar-bg); }
	.logo-wrap { flex: 1; min-width: 0; }
	.logo { font-size: 1rem; font-weight: 700; }
	.convoy-name { font-size: var(--text-xs); color: var(--text-2); margin-top: .25rem; }
	.org-name { font-size: var(--text-xs); color: var(--text-muted); margin-top: .1rem; }

	/* WS indicator */
	.ws-indicator { display: flex; align-items: center; gap: .35rem; font-size: var(--text-xs); color: var(--text-muted); flex-shrink: 0; }
	.ws-dot { width: 8px; height: 8px; border-radius: 50%; background: #e74c3c; flex-shrink: 0; }
	.ws-dot.connected { background: #27ae60; animation: pulse 2s infinite; }
	.ws-label { white-space: nowrap; }

	/* Error bar */
	.error-bar { background: var(--color-primary-hover); color: white; padding: .4rem .75rem; font-size: var(--text-xs); margin: 0; display: flex; justify-content: space-between; align-items: flex-start; gap: .5rem; flex-shrink: 0; word-break: break-word; }
	.error-bar button { background: none; border: none; color: white; cursor: pointer; font-size: 1rem; flex-shrink: 0; line-height: 1; padding: 0; }

	/* Position block */
	.position-block { padding: .75rem 1rem; border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: .5rem; flex-shrink: 0; }
	.position-label { font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); }
	.position-block select { width: 100%; padding: .5rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
	.position-block select:disabled { opacity: .6; }

	.btn-primary { width: 100%; padding: .5rem 1rem; background: var(--color-primary); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
	.btn-primary:disabled { opacity: .5; cursor: not-allowed; }
	.btn-primary:hover:not(:disabled) { background: var(--color-primary-hover); }
	.btn-stop { width: 100%; padding: .5rem 1rem; background: rgba(226,61,40,.3); border: 1px solid var(--color-primary); color: var(--text-1); border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }

	.hint { font-size: var(--text-xs); color: var(--text-muted); font-style: italic; margin: 0; line-height: 1.4; }
	.hint.hint-active { color: #f1c40f; font-style: normal; }

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
	.status-select { max-width: 110px; font-size: var(--text-xs); padding: .2rem .3rem; border: 1.5px solid; border-radius: 3px; background: var(--surface-2); color: var(--text-1); }

	/* Schedule table */
	.schedule-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
	.schedule-table th, .schedule-table td { padding: .5rem; text-align: left; border-bottom: 1px solid var(--border); }
	.schedule-table th { color: var(--text-muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .04em; }

	/* Map */
	.map-area { flex: 1; position: relative; }
	.map-area.cursor-crosshair :global(.maplibregl-canvas) { cursor: crosshair; }
	.map-hint-bar { position: absolute; top: 1rem; left: 50%; transform: translateX(-50%); z-index: 10; background: rgba(15,27,36,.9); color: white; padding: .5rem 1.2rem; border-radius: 20px; font-size: var(--text-sm); pointer-events: none; white-space: nowrap; }

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
