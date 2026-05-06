<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import MapView from '$lib/components/MapView.svelte';
	import InfoPill from '$lib/components/InfoPill.svelte';
	import { convoysApi, trackingApi, type Convoy, type VehiclePosition } from '$lib/api';
	import { livePositions, vehicleStatuses, connectTracking, disconnectTracking, sendPosition, trackingActive } from '$lib/stores/tracking';

	const convoyId = $page.params.convoy_id;

	let convoy = $state<Convoy | null>(null);
	let myVehicleId = $state('');
	let transmitting = $state(false);
	let geoWatcher: number | null = null;
	let mapCenter = $state<[number, number]>([10.0, 51.5]);
	let error = $state('');

	const STATUS_LABELS = { planned:'Geplant', en_route:'Unterwegs', arrived:'Angekommen', delayed:'Verspätung' };
	const STATUS_COLORS = { planned:'#95a5a6', en_route:'#3498db', arrived:'#27ae60', delayed:'#e74c3c' };

	onMount(async () => {
		try {
			convoy = await convoysApi.get(convoyId);
			// Load existing positions
			const positions = await trackingApi.getPositions(convoyId);
			livePositions.set(new Map(positions.map(p => [p.vehicle_id, p])));
			// Connect WebSocket
			connectTracking(convoyId);
		} catch (e) {
			error = 'Convoy nicht geladen';
		}
	});

	onDestroy(() => {
		disconnectTracking();
		stopTransmitting();
	});

	function startTransmitting() {
		if (!myVehicleId) { error = 'Bitte zuerst ein Fahrzeug auswählen'; return; }
		transmitting = true;
		geoWatcher = navigator.geolocation.watchPosition(
			(pos) => {
				const { latitude: lat, longitude: lon, speed, heading } = pos.coords;
				sendPosition(convoyId, myVehicleId, lat, lon, speed ? speed * 3.6 : undefined, heading ?? undefined);
			},
			(e) => { error = `GPS-Fehler: ${e.message}`; },
			{ enableHighAccuracy: true, maximumAge: 5000 }
		);
	}

	function stopTransmitting() {
		if (geoWatcher !== null) { navigator.geolocation.clearWatch(geoWatcher); geoWatcher = null; }
		transmitting = false;
	}

	async function setStatus(vehicleId: string, status: string) {
		try {
			await trackingApi.updateVehicleStatus(convoyId, vehicleId, status);
		} catch { error = 'Status konnte nicht aktualisiert werden'; }
	}

	function formatTime(iso: string | null) {
		if (!iso) return '–';
		return new Date(iso).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
	}
</script>

<div class="tracking-app">
	<!-- Sidebar -->
	<aside class="sidebar">
		<div class="sidebar-header">
			<div>
				<h1>{convoy?.name ?? 'Laden…'}</h1>
				{#if convoy?.organization}<p>{convoy.organization}</p>{/if}
			</div>
			<div class="ws-indicator" class:connected={$trackingActive} title={$trackingActive ? 'Verbunden' : 'Nicht verbunden'}>
				{$trackingActive ? '🟢' : '🔴'}
			</div>
		</div>

		{#if error}<p class="error">{error}</p>{/if}

		<!-- Meine Position senden -->
		<div class="section">
			<strong>Meine Position</strong>
			<select bind:value={myVehicleId}>
				<option value="">Fahrzeug wählen…</option>
				{#each (convoy?.convoy_vehicles ?? []) as cv}
					<option value={cv.vehicle.id}>{cv.vehicle.name} {cv.vehicle.callsign ? `(${cv.vehicle.callsign})` : ''}</option>
				{/each}
			</select>
			{#if !transmitting}
				<button class="btn-start" onclick={startTransmitting} disabled={!myVehicleId}>
					📡 Position senden starten
				</button>
			{:else}
				<button class="btn-stop" onclick={stopTransmitting}>⏹ Senden stoppen</button>
			{/if}
		</div>

		<!-- Fahrzeugstatus -->
		<div class="section">
			<strong>Fahrzeugstatus</strong>
			{#each (convoy?.convoy_vehicles ?? []) as cv}
				<div class="vehicle-row">
					<div class="vehicle-info">
						<span class="vname">{cv.vehicle.name}</span>
						{#if cv.vehicle.callsign}<span class="tag">{cv.vehicle.callsign}</span>{/if}
						{#if $livePositions.has(cv.vehicle.id)}
							<span class="live-badge">LIVE</span>
						{/if}
					</div>
					<select
						class="status-select"
						value={$vehicleStatuses.get(cv.vehicle.id) ?? cv.vehicle_status}
						onchange={(e) => setStatus(cv.vehicle.id, (e.target as HTMLSelectElement).value)}
						style="border-color:{STATUS_COLORS[($vehicleStatuses.get(cv.vehicle.id) ?? cv.vehicle_status) as keyof typeof STATUS_COLORS] ?? '#95a5a6'}"
					>
						{#each Object.entries(STATUS_LABELS) as [val, label]}
							<option value={val}>{label}</option>
						{/each}
					</select>
				</div>
			{/each}
		</div>

		<!-- Zeitplan -->
		{#if convoy?.waypoints.some(w => w.planned_arrival)}
			<div class="section">
				<strong>Zeitplan</strong>
				<table class="schedule">
					<thead><tr><th>Wegpunkt</th><th>Ankunft</th><th>Abfahrt</th></tr></thead>
					<tbody>
						{#each convoy.waypoints as wp}
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
	</aside>

	<!-- Karte -->
	<main class="map-area">
		<InfoPill startPoint={{ lat: mapCenter[0], lon: mapCenter[1] }} />
		<MapView
			startPoint={convoy?.start_point}
			endPoint={convoy?.end_point}
			waypoints={convoy?.waypoints ?? []}
			livePositions={$livePositions}
			onMapMove={(lat, lon) => (mapCenter = [lat, lon])}
		/>
	</main>
</div>

<style>
	:global(body) { margin: 0; font-family: system-ui, sans-serif; }
	.tracking-app { display: flex; height: 100vh; }

	.sidebar { width: 300px; background: #1a2744; color: white; padding: 1rem; overflow-y: auto; display: flex; flex-direction: column; gap: .75rem; }
	.sidebar-header { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 1px solid rgba(255,255,255,.15); padding-bottom: .75rem; }
	.sidebar-header h1 { margin: 0; font-size: 1rem; }
	.sidebar-header p { margin: .2rem 0 0; font-size: .8rem; color: rgba(255,255,255,.6); }
	.ws-indicator { font-size: 1.2rem; }

	.section { background: rgba(255,255,255,.05); border-radius: 6px; padding: .6rem; }
	.section strong { display: block; font-size: .82rem; margin-bottom: .4rem; }

	select { width: 100%; padding: .4rem; border-radius: 4px; border: none; background: rgba(255,255,255,.12); color: white; margin-bottom: .4rem; font-size: .82rem; }

	.btn-start { width: 100%; padding: .5rem; background: #27ae60; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; font-size: .85rem; }
	.btn-start:disabled { opacity: .5; cursor: not-allowed; }
	.btn-stop { width: 100%; padding: .5rem; background: #e74c3c; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; font-size: .85rem; }

	.vehicle-row { display: flex; align-items: center; justify-content: space-between; padding: .3rem 0; border-bottom: 1px solid rgba(255,255,255,.07); gap: .4rem; }
	.vehicle-info { display: flex; align-items: center; gap: .25rem; flex: 1; min-width: 0; }
	.vname { font-size: .82rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.tag { display: inline-block; padding: .05rem .25rem; background: rgba(255,255,255,.15); border-radius: 3px; font-size: .68rem; }
	.live-badge { background: #27ae60; color: white; border-radius: 3px; padding: .05rem .25rem; font-size: .65rem; font-weight: 700; animation: pulse 1.5s infinite; }
	.status-select { max-width: 110px; font-size: .75rem; padding: .2rem .3rem; border: 1.5px solid; }

	.schedule { width: 100%; border-collapse: collapse; font-size: .78rem; }
	.schedule th, .schedule td { padding: .25rem .3rem; border-bottom: 1px solid rgba(255,255,255,.1); }
	.schedule th { color: rgba(255,255,255,.6); }

	.error { background: #c0392b; border-radius: 4px; padding: .4rem .6rem; font-size: .8rem; }

	.map-area { flex: 1; position: relative; }

	@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .5; } }
</style>
