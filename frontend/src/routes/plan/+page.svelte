<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import MapView from '$lib/components/MapView.svelte';
	import { auth } from '$lib/stores/auth';
	import { activeConvoy, activeRoute, convoys } from '$lib/stores/convoy';
	import { mapMode } from '$lib/stores/map';
	import { convoysApi, vehiclesApi, type Convoy, type Vehicle, type Waypoint } from '$lib/api';

	let allVehicles = $state<Vehicle[]>([]);
	let convoyList = $state<Convoy[]>([]);
	let selected = $state<Convoy | null>(null);
	let route = $state<{ geojson: GeoJSON.Geometry | null; distance_m: number | null; duration_s: number | null } | null>(null);

	// Modals / panel state
	let showVehicleForm = $state(false);
	let showConvoyForm = $state(false);
	let newVehicle = $state({ name: '', callsign: '', license_plate: '', height_cm: '', weight_kg: '', length_cm: '', convoy_role: '' });
	let newConvoy = $state({ name: '', organization: '', start_time: '', speed_urban_kmh: 50, speed_rural_kmh: 80 });
	let activeTab = $state<'convoy' | 'vehicles' | 'waypoints' | 'schedule'>('convoy');
	let loading = $state(false);
	let error = $state('');

	onMount(async () => {
		await loadData();
	});

	async function loadData() {
		try {
			[allVehicles, convoyList] = await Promise.all([vehiclesApi.list(), convoysApi.list()]);
			convoys.set(convoyList);
			if (!selected && convoyList.length) selectConvoy(convoyList[0]);
		} catch (e) {
			error = 'Fehler beim Laden der Daten';
		}
	}

	function selectConvoy(c: Convoy) {
		selected = c;
		activeConvoy.set(c);
		route = null;
		activeRoute.set(null);
	}

	async function createVehicle() {
		try {
			const v = await vehiclesApi.create({
				...newVehicle,
				height_cm: newVehicle.height_cm ? Number(newVehicle.height_cm) : undefined,
				weight_kg: newVehicle.weight_kg ? Number(newVehicle.weight_kg) : undefined,
				length_cm: newVehicle.length_cm ? Number(newVehicle.length_cm) : undefined,
			} as never);
			allVehicles = [...allVehicles, v];
			newVehicle = { name: '', callsign: '', license_plate: '', height_cm: '', weight_kg: '', length_cm: '', convoy_role: '' };
			showVehicleForm = false;
		} catch (e) {
			error = 'Fahrzeug konnte nicht erstellt werden';
		}
	}

	async function createConvoy() {
		try {
			const c = await convoysApi.create({
				name: newConvoy.name,
				organization: newConvoy.organization || undefined,
				start_time: newConvoy.start_time || undefined,
				speed_urban_kmh: newConvoy.speed_urban_kmh,
				speed_rural_kmh: newConvoy.speed_rural_kmh,
			});
			convoyList = [...convoyList, c];
			convoys.set(convoyList);
			selectConvoy(c);
			showConvoyForm = false;
		} catch (e) {
			error = 'Marschverband konnte nicht erstellt werden';
		}
	}

	async function addVehicleToConvoy(vehicleId: string) {
		if (!selected) return;
		try {
			await convoysApi.addVehicle(selected.id, vehicleId, selected.convoy_vehicles.length);
			await refreshConvoy();
		} catch (e) { error = 'Fehler beim Hinzufügen'; }
	}

	async function removeVehicleFromConvoy(vehicleId: string) {
		if (!selected) return;
		try {
			await convoysApi.removeVehicle(selected.id, vehicleId);
			await refreshConvoy();
		} catch (e) { error = 'Fehler beim Entfernen'; }
	}

	async function refreshConvoy() {
		if (!selected) return;
		selected = await convoysApi.get(selected.id);
		convoyList = convoyList.map((c) => (c.id === selected!.id ? selected! : c));
		convoys.set(convoyList);
		activeConvoy.set(selected);
	}

	async function handleMapClick(lat: number, lon: number) {
		if (!selected) return;
		const mode = $mapMode;
		if (mode === 'set-start') {
			await convoysApi.update(selected.id, { start_point: { lat, lon } } as never);
			mapMode.set('idle');
		} else if (mode === 'set-end') {
			await convoysApi.update(selected.id, { end_point: { lat, lon } } as never);
			mapMode.set('idle');
		} else if (mode === 'add-waypoint') {
			const name = prompt('Wegpunktname:') ?? `WP ${selected.waypoints.length + 1}`;
			await convoysApi.createWaypoint(selected.id, { name, lat, lon, type: 'waypoint', order_index: selected.waypoints.length });
			mapMode.set('idle');
		}
		await refreshConvoy();
	}

	async function deleteWaypoint(wpId: string) {
		if (!selected) return;
		await convoysApi.deleteWaypoint(selected.id, wpId);
		await refreshConvoy();
	}

	async function calculateRoute() {
		if (!selected) return;
		loading = true;
		error = '';
		try {
			const r = await convoysApi.calculateRoute(selected.id);
			route = { geojson: r.geojson, distance_m: r.distance_m, duration_s: r.duration_s };
			activeRoute.set(r);
			await refreshConvoy();
			activeTab = 'schedule';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Routing fehlgeschlagen';
		} finally {
			loading = false;
		}
	}

	function formatDuration(s: number | null) {
		if (!s) return '–';
		const h = Math.floor(s / 3600);
		const m = Math.floor((s % 3600) / 60);
		return h > 0 ? `${h} h ${m} min` : `${m} min`;
	}

	function formatTime(iso: string | null) {
		if (!iso) return '–';
		return new Date(iso).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
	}

	function logout() {
		auth.logout();
		goto('/login');
	}

	$: assignedIds = new Set(selected?.convoy_vehicles.map((cv) => cv.vehicle.id) ?? []);
	$: exportToken = selected?.id;
	$: apiBase = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
</script>

<div class="app">
	<!-- Sidebar -->
	<aside class="sidebar">
		<div class="sidebar-header">
			<span class="logo">MarschPlan</span>
			<button class="logout-btn" onclick={logout} title="Abmelden">✕</button>
		</div>

		<!-- Convoy selector -->
		<div class="convoy-selector">
			<select onchange={(e) => { const c = convoyList.find(x => x.id === (e.target as HTMLSelectElement).value); if (c) selectConvoy(c); }}>
				{#if convoyList.length === 0}
					<option value="">Kein Marschverband</option>
				{/if}
				{#each convoyList as c}
					<option value={c.id} selected={selected?.id === c.id}>{c.name}</option>
				{/each}
			</select>
			<button class="btn-small" onclick={() => (showConvoyForm = true)}>+ Neu</button>
		</div>

		<!-- Tabs -->
		<div class="tabs">
			{#each [['convoy', 'Verband'], ['vehicles', 'Fahrzeuge'], ['waypoints', 'Wegpunkte'], ['schedule', 'Zeitplan']] as [tab, label]}
				<button class="tab" class:active={activeTab === tab} onclick={() => (activeTab = tab as typeof activeTab)}>{label}</button>
			{/each}
		</div>

		<div class="tab-content">
			<!-- Convoy Tab -->
			{#if activeTab === 'convoy' && selected}
				<div class="section">
					<p><strong>Organisation:</strong> {selected.organization ?? '–'}</p>
					<p><strong>Startzeit:</strong> {selected.start_time ? new Date(selected.start_time).toLocaleString('de-DE') : '–'}</p>
					<p><strong>Geschwindigkeit:</strong> {selected.speed_urban_kmh} km/h (innerorts) / {selected.speed_rural_kmh} km/h (außerorts)</p>
				</div>
				<div class="map-actions">
					<button class="btn-map" class:active={$mapMode === 'set-start'} onclick={() => mapMode.set($mapMode === 'set-start' ? 'idle' : 'set-start')}>
						📍 Start setzen
					</button>
					<button class="btn-map" class:active={$mapMode === 'set-end'} onclick={() => mapMode.set($mapMode === 'set-end' ? 'idle' : 'set-end')}>
						🏁 Ziel setzen
					</button>
					<button class="btn-map" class:active={$mapMode === 'add-waypoint'} onclick={() => mapMode.set($mapMode === 'add-waypoint' ? 'idle' : 'add-waypoint')}>
						➕ Wegpunkt
					</button>
				</div>
				{#if $mapMode !== 'idle'}
					<p class="hint">Klick auf die Karte, um den Punkt zu setzen.</p>
				{/if}
				<div class="route-actions">
					<button class="btn-primary" onclick={calculateRoute} disabled={loading}>
						{loading ? 'Berechne…' : '🗺 Route berechnen'}
					</button>
					{#if route}
						<p class="route-info">
							{(route.distance_m! / 1000).toFixed(1)} km · {formatDuration(route.duration_s)}
						</p>
						<a class="btn-export" href="{apiBase}/api/convoys/{exportToken}/export/gpx" target="_blank">⬇ GPX</a>
						<a class="btn-export" href="{apiBase}/api/convoys/{exportToken}/export/json" target="_blank">⬇ JSON</a>
						<button class="btn-export" onclick={() => navigator.clipboard.writeText(`${window.location.origin}/share/${selected?.share_token}`)}>
							🔗 Link kopieren
						</button>
					{/if}
				</div>
			{/if}

			<!-- Vehicles Tab -->
			{#if activeTab === 'vehicles'}
				<div class="section">
					<div class="section-header">
						<strong>Meine Fahrzeuge</strong>
						<button class="btn-small" onclick={() => (showVehicleForm = !showVehicleForm)}>+ Neu</button>
					</div>
					{#if showVehicleForm}
						<form class="inline-form" onsubmit={(e) => { e.preventDefault(); createVehicle(); }}>
							<input placeholder="Name *" bind:value={newVehicle.name} required />
							<input placeholder="Funkrufname" bind:value={newVehicle.callsign} />
							<input placeholder="Kennzeichen" bind:value={newVehicle.license_plate} />
							<input placeholder="Höhe (cm)" type="number" bind:value={newVehicle.height_cm} />
							<input placeholder="Gewicht (kg)" type="number" bind:value={newVehicle.weight_kg} />
							<input placeholder="Länge (cm)" type="number" bind:value={newVehicle.length_cm} />
							<input placeholder="Funktion im Konvoi" bind:value={newVehicle.convoy_role} />
							<button type="submit">Speichern</button>
						</form>
					{/if}
					<ul class="vehicle-list">
						{#each allVehicles as v}
							<li class="vehicle-item">
								<div>
									<strong>{v.name}</strong>
									{#if v.callsign}<span class="tag">{v.callsign}</span>{/if}
									{#if v.license_plate}<span class="tag">{v.license_plate}</span>{/if}
								</div>
								{#if selected}
									{#if assignedIds.has(v.id)}
										<button class="btn-small danger" onclick={() => removeVehicleFromConvoy(v.id)}>Entfernen</button>
									{:else}
										<button class="btn-small" onclick={() => addVehicleToConvoy(v.id)}>Zuweisen</button>
									{/if}
								{/if}
							</li>
						{/each}
					</ul>
					{#if selected && selected.convoy_vehicles.length > 0}
						<div class="section-header" style="margin-top:1rem"><strong>Im Verband ({selected.convoy_vehicles.length})</strong></div>
						<ol class="vehicle-list">
							{#each selected.convoy_vehicles as cv}
								<li class="vehicle-item">
									<span>{cv.position + 1}. {cv.vehicle.name}</span>
									{#if cv.vehicle.callsign}<span class="tag">{cv.vehicle.callsign}</span>{/if}
								</li>
							{/each}
						</ol>
					{/if}
				</div>
			{/if}

			<!-- Waypoints Tab -->
			{#if activeTab === 'waypoints' && selected}
				<div class="section">
					<div class="section-header">
						<strong>Wegpunkte</strong>
						<button class="btn-small" class:active={$mapMode === 'add-waypoint'} onclick={() => mapMode.set($mapMode === 'add-waypoint' ? 'idle' : 'add-waypoint')}>
							+ Auf Karte
						</button>
					</div>
					{#if selected.waypoints.length === 0}
						<p class="hint">Noch keine Wegpunkte. Klick auf „+ Auf Karte" und dann auf die Karte.</p>
					{/if}
					<ul class="wp-list">
						{#each selected.waypoints as wp}
							<li class="wp-item">
								<div>
									<strong>{wp.name}</strong>
									<span class="tag">{wp.type}</span>
									{#if wp.hold_duration_min > 0}<span class="tag">{wp.hold_duration_min} min</span>{/if}
								</div>
								<button class="btn-small danger" onclick={() => deleteWaypoint(wp.id)}>✕</button>
							</li>
						{/each}
					</ul>
				</div>
			{/if}

			<!-- Schedule Tab -->
			{#if activeTab === 'schedule' && selected}
				<div class="section">
					<strong>Zeitplan</strong>
					{#if selected.waypoints.some(w => w.planned_arrival)}
						<table class="schedule-table">
							<thead>
								<tr><th>Wegpunkt</th><th>Ankunft</th><th>Abfahrt</th></tr>
							</thead>
							<tbody>
								{#each selected.waypoints as wp}
									<tr>
										<td>{wp.name}</td>
										<td>{formatTime(wp.planned_arrival)}</td>
										<td>{formatTime(wp.planned_departure)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					{:else}
						<p class="hint">Zeitplan wird nach Routenberechnung angezeigt.</p>
					{/if}
				</div>
			{/if}
		</div>

		{#if error}
			<p class="error-bar">{error}</p>
		{/if}
	</aside>

	<!-- Map -->
	<main class="map-area">
		{#if $mapMode !== 'idle'}
			<div class="map-hint-bar">
				{#if $mapMode === 'set-start'}Klick auf die Karte, um den Startpunkt zu setzen{/if}
				{#if $mapMode === 'set-end'}Klick auf die Karte, um den Zielpunkt zu setzen{/if}
				{#if $mapMode === 'add-waypoint'}Klick auf die Karte, um einen Wegpunkt hinzuzufügen{/if}
				<button onclick={() => mapMode.set('idle')}>Abbrechen</button>
			</div>
		{/if}
		<MapView
			startPoint={selected?.start_point}
			endPoint={selected?.end_point}
			waypoints={selected?.waypoints ?? []}
			routeGeojson={route?.geojson}
			{onMapClick}
		/>
	</main>
</div>

<!-- Create Convoy Modal -->
{#if showConvoyForm}
	<div class="modal-backdrop" onclick={() => (showConvoyForm = false)}>
		<div class="modal" onclick={(e) => e.stopPropagation()}>
			<h2>Neuer Marschverband</h2>
			<form onsubmit={(e) => { e.preventDefault(); createConvoy(); }}>
				<label>Name<input bind:value={newConvoy.name} required /></label>
				<label>Organisation<input bind:value={newConvoy.organization} /></label>
				<label>Startzeit<input type="datetime-local" bind:value={newConvoy.start_time} /></label>
				<label>Geschwindigkeit innerorts (km/h)<input type="number" bind:value={newConvoy.speed_urban_kmh} /></label>
				<label>Geschwindigkeit außerorts (km/h)<input type="number" bind:value={newConvoy.speed_rural_kmh} /></label>
				<div class="modal-actions">
					<button type="button" onclick={() => (showConvoyForm = false)}>Abbrechen</button>
					<button type="submit" class="btn-primary">Erstellen</button>
				</div>
			</form>
		</div>
	</div>
{/if}

<style>
	:global(body) { margin: 0; font-family: system-ui, sans-serif; }

	.app { display: flex; height: 100vh; overflow: hidden; }

	.sidebar {
		width: 340px;
		min-width: 280px;
		background: #1a2744;
		color: white;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.sidebar-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 1rem;
		border-bottom: 1px solid rgba(255,255,255,.15);
	}
	.logo { font-size: 1.1rem; font-weight: 700; letter-spacing: .5px; }
	.logout-btn { background: none; border: none; color: rgba(255,255,255,.6); cursor: pointer; font-size: 1rem; }

	.convoy-selector {
		display: flex;
		gap: .5rem;
		padding: .75rem 1rem;
		border-bottom: 1px solid rgba(255,255,255,.1);
	}
	.convoy-selector select {
		flex: 1;
		padding: .4rem;
		border-radius: 4px;
		border: none;
		background: rgba(255,255,255,.12);
		color: white;
	}

	.tabs { display: flex; border-bottom: 1px solid rgba(255,255,255,.1); }
	.tab {
		flex: 1;
		padding: .6rem .25rem;
		background: none;
		border: none;
		color: rgba(255,255,255,.6);
		font-size: .75rem;
		cursor: pointer;
		border-bottom: 2px solid transparent;
	}
	.tab.active { color: white; border-bottom-color: #e74c3c; }

	.tab-content { flex: 1; overflow-y: auto; padding: .75rem 1rem; }

	.section { margin-bottom: 1rem; }
	.section p { margin: .3rem 0; font-size: .85rem; color: rgba(255,255,255,.85); }
	.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: .5rem; }

	.map-actions { display: flex; flex-wrap: wrap; gap: .4rem; margin-bottom: .5rem; }
	.btn-map {
		padding: .4rem .6rem;
		background: rgba(255,255,255,.1);
		border: 1px solid rgba(255,255,255,.2);
		color: white;
		border-radius: 4px;
		font-size: .8rem;
		cursor: pointer;
	}
	.btn-map.active { background: #e74c3c; border-color: #e74c3c; }

	.btn-primary {
		width: 100%;
		padding: .6rem;
		background: #e74c3c;
		color: white;
		border: none;
		border-radius: 4px;
		font-weight: 600;
		cursor: pointer;
		font-size: .9rem;
	}
	.btn-primary:disabled { opacity: .5; cursor: not-allowed; }

	.btn-small {
		padding: .25rem .5rem;
		background: rgba(255,255,255,.15);
		border: 1px solid rgba(255,255,255,.25);
		color: white;
		border-radius: 4px;
		font-size: .78rem;
		cursor: pointer;
	}
	.btn-small.danger { background: rgba(231,76,60,.3); border-color: #e74c3c; }
	.btn-small.active { background: #e74c3c; }

	.btn-export {
		display: inline-block;
		margin: .25rem .25rem 0 0;
		padding: .3rem .6rem;
		background: rgba(255,255,255,.1);
		border: 1px solid rgba(255,255,255,.2);
		color: white;
		border-radius: 4px;
		font-size: .78rem;
		text-decoration: none;
		cursor: pointer;
	}

	.route-actions { margin-top: .75rem; }
	.route-info { font-size: .85rem; color: rgba(255,255,255,.8); margin: .4rem 0; }

	.hint { font-size: .8rem; color: rgba(255,255,255,.5); font-style: italic; margin: .25rem 0; }

	.vehicle-list { list-style: none; padding: 0; margin: 0; }
	.vehicle-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: .4rem 0;
		border-bottom: 1px solid rgba(255,255,255,.08);
		font-size: .85rem;
	}

	.tag {
		display: inline-block;
		padding: .1rem .35rem;
		background: rgba(255,255,255,.15);
		border-radius: 3px;
		font-size: .72rem;
		margin-left: .25rem;
	}

	.wp-list { list-style: none; padding: 0; margin: 0; }
	.wp-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: .4rem 0;
		border-bottom: 1px solid rgba(255,255,255,.08);
		font-size: .85rem;
	}

	.schedule-table { width: 100%; border-collapse: collapse; font-size: .82rem; }
	.schedule-table th, .schedule-table td { padding: .3rem .4rem; text-align: left; border-bottom: 1px solid rgba(255,255,255,.1); }
	.schedule-table th { color: rgba(255,255,255,.6); font-weight: 600; }

	.inline-form { display: flex; flex-direction: column; gap: .4rem; margin-bottom: .75rem; }
	.inline-form input {
		padding: .4rem;
		border-radius: 4px;
		border: none;
		background: rgba(255,255,255,.12);
		color: white;
		font-size: .85rem;
	}
	.inline-form input::placeholder { color: rgba(255,255,255,.4); }
	.inline-form button {
		padding: .4rem;
		background: #27ae60;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
	}

	.error-bar {
		background: #c0392b;
		color: white;
		padding: .5rem 1rem;
		font-size: .82rem;
		margin: 0;
	}

	.map-area { flex: 1; position: relative; }
	.map-hint-bar {
		position: absolute;
		top: 1rem;
		left: 50%;
		transform: translateX(-50%);
		z-index: 10;
		background: rgba(26,39,68,.9);
		color: white;
		padding: .5rem 1rem;
		border-radius: 20px;
		display: flex;
		align-items: center;
		gap: 1rem;
		font-size: .85rem;
	}
	.map-hint-bar button {
		background: rgba(255,255,255,.2);
		border: none;
		color: white;
		border-radius: 12px;
		padding: .2rem .6rem;
		cursor: pointer;
	}

	/* Modal */
	.modal-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0,0,0,.5);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
	}
	.modal {
		background: white;
		border-radius: 8px;
		padding: 2rem;
		width: 100%;
		max-width: 420px;
		color: #333;
	}
	.modal h2 { margin: 0 0 1.25rem; }
	.modal label { display: flex; flex-direction: column; gap: .25rem; margin-bottom: .75rem; font-size: .85rem; font-weight: 600; }
	.modal input { padding: .5rem; border: 1px solid #ccc; border-radius: 4px; font-size: 1rem; }
	.modal-actions { display: flex; justify-content: flex-end; gap: .5rem; margin-top: 1rem; }
	.modal-actions button { padding: .5rem 1rem; border-radius: 4px; cursor: pointer; border: 1px solid #ccc; }
	.modal-actions .btn-primary { background: #1a2744; color: white; border-color: #1a2744; }
</style>
