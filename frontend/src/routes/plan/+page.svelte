<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import MapView from '$lib/components/MapView.svelte';
	import LocationSearch from '$lib/components/LocationSearch.svelte';
	import WeatherWidget from '$lib/components/WeatherWidget.svelte';
	import LageLayerPanel from '$lib/components/LageLayerPanel.svelte';
	import ServiceStatus from '$lib/components/ServiceStatus.svelte';
	import { get } from 'svelte/store';
	import { auth } from '$lib/stores/auth';
	import { activeConvoy, activeRoute, convoys } from '$lib/stores/convoy';
	import { lageLayers } from '$lib/stores/lage';
	import { mapMode } from '$lib/stores/map';
	import {
		convoysApi, vehiclesApi, orgsApi, overpassApi,
		type Convoy, type Vehicle, type Organization, type LageLayer,
		type FuelAnalysis, type FuelStation, type Waypoint, type RoadPreference,
	} from '$lib/api';
	import type { FeatureCollection } from 'geojson';

	// ── State ──────────────────────────────────────────────────────────
	let allVehicles = $state<Vehicle[]>([]);
	let convoyList = $state<Convoy[]>([]);
	let organizations = $state<Organization[]>([]);
	let selected = $state<Convoy | null>(null);
	let route = $state<{ geojson: unknown; distance_m: number | null; duration_s: number | null; fuel_analysis: FuelAnalysis | null } | null>(null);
	let fuelStations = $state<FuelStation[]>([]);
	let showFuelStations = $state(false);
	let fuelStationsLoading = $state(false);
	let closures = $state<FeatureCollection | null>(null);
	let showClosures = $state(false);
	let mapCenter = $state<[number, number]>([10.0, 51.5]);
	let activeTab = $state<'convoy'|'fahrzeuge'|'wegpunkte'|'zeitplan'|'export'|'lage'|'org'>('convoy');
	let loading = $state(false);
	let sidebarOpen = $state(false);
	let error = $state('');

	// Forms
	let showVehicleForm = $state(false);
	let showConvoyForm = $state(false);
	let showSubConvoyForm = $state(false);
	let newVehicle = $state({ name:'', callsign:'', license_plate:'', height_cm:'', weight_kg:'', length_cm:'', convoy_role:'', tank_capacity_l:'', fuel_consumption_l100km:'', current_fuel_l:'' });
	let newConvoy = $state(defaultConvoyForm());
	let newWpForm = $state({ name:'', type:'waypoint', hold_duration_min:0, halt_purpose:'' });
	let pendingWpClick = $state(false);
	let wizardStep = $state<0 | 1 | 2 | 3>(0);
	let wizardWpName = $state('');

	function defaultConvoyForm() {
		return { name:'', organization:'', organization_id:'', start_time:'', speed_urban_kmh:40, speed_rural_kmh:65, road_preference:'schnell' as RoadPreference, spacing_urban_m:15, spacing_rural_m:50, spacing_motorway_m:100, lage:'', auftrag:'', marschform:'geschlossener_verband', ablaufpunkt:'', ablaufzeit:'', ablaufführer:'', versorgung:'', funkgruppe:'', anlagen:'' };
	}

	// ── Init ──────────────────────────────────────────────────────────
	onMount(async () => {
		await loadData();
	});

	async function loadData() {
		try {
			[allVehicles, convoyList, organizations] = await Promise.all([
				vehiclesApi.list(), convoysApi.list(), orgsApi.list(),
			]);
			convoys.set(convoyList);
			if (!selected && convoyList.length) selectConvoy(convoyList[0]);
		} catch { error = 'Fehler beim Laden'; }
	}

	function selectConvoy(c: Convoy) {
		selected = c;
		activeConvoy.set(c);
		route = null;
		activeRoute.set(null);
	}

	async function refreshConvoy() {
		if (!selected) return;
		selected = await convoysApi.get(selected.id);
		convoyList = convoyList.map(c => c.id === selected!.id ? selected! : c);
		convoys.set(convoyList);
		activeConvoy.set(selected);
	}

	// ── Convoy CRUD ─────────────────────────────────────────────────
	async function createConvoy() {
		try {
			const c = await convoysApi.create({
				name: newConvoy.name,
				organization: newConvoy.organization || undefined,
				organization_id: newConvoy.organization_id || undefined,
				start_time: newConvoy.start_time || undefined,
				speed_urban_kmh: newConvoy.speed_urban_kmh,
				speed_rural_kmh: newConvoy.speed_rural_kmh,
				road_preference: newConvoy.road_preference,
				spacing_urban_m: newConvoy.spacing_urban_m,
				spacing_rural_m: newConvoy.spacing_rural_m,
				spacing_motorway_m: newConvoy.spacing_motorway_m,
			});
			convoyList = [...convoyList, c];
			convoys.set(convoyList);
			selectConvoy(c);
			showConvoyForm = false;
			newConvoy = defaultConvoyForm();
			wizardStep = 1;
			mapMode.set('set-start');
		} catch { error = 'Konvoi konnte nicht erstellt werden'; }
	}

	// ── Vehicles ─────────────────────────────────────────────────────
	async function createVehicle() {
		try {
			const v = await vehiclesApi.create({
				...newVehicle,
				height_cm: newVehicle.height_cm ? Number(newVehicle.height_cm) : undefined,
				weight_kg: newVehicle.weight_kg ? Number(newVehicle.weight_kg) : undefined,
				length_cm: newVehicle.length_cm ? Number(newVehicle.length_cm) : undefined,
				tank_capacity_l: newVehicle.tank_capacity_l ? Number(newVehicle.tank_capacity_l) : undefined,
				fuel_consumption_l100km: newVehicle.fuel_consumption_l100km ? Number(newVehicle.fuel_consumption_l100km) : undefined,
				current_fuel_l: newVehicle.current_fuel_l ? Number(newVehicle.current_fuel_l) : undefined,
			} as never);
			allVehicles = [...allVehicles, v];
			newVehicle = { name:'', callsign:'', license_plate:'', height_cm:'', weight_kg:'', length_cm:'', convoy_role:'', tank_capacity_l:'', fuel_consumption_l100km:'', current_fuel_l:'' };
			showVehicleForm = false;
		} catch { error = 'Fahrzeug konnte nicht erstellt werden'; }
	}

	let vehicleSonderfunktion = $state<Record<string, string>>({});

	async function addVehicleToConvoy(vehicleId: string) {
		if (!selected) return;
		try {
			const sf = vehicleSonderfunktion[vehicleId] || undefined;
			await convoysApi.addVehicle(selected.id, vehicleId, selected.convoy_vehicles.length, sf);
			await refreshConvoy();
		} catch { error = 'Fehler beim Hinzufügen'; }
	}

	async function removeVehicleFromConvoy(vehicleId: string) {
		if (!selected) return;
		try {
			await convoysApi.removeVehicle(selected.id, vehicleId);
			await refreshConvoy();
		} catch { error = 'Fehler beim Entfernen'; }
	}

	// ── Map Click Handler ─────────────────────────────────────────────
	async function handleMapClick(lat: number, lon: number) {
		if (!selected) { error = 'Kein Verband ausgewählt'; return; }
		const mode = get(mapMode);
		try {
			if (mode === 'set-start') {
				await convoysApi.update(selected.id, { start_point: { lat, lon } });
				mapMode.set('idle');
				if (wizardStep === 1) { wizardStep = 2; mapMode.set('set-end'); }
			} else if (mode === 'set-end') {
				await convoysApi.update(selected.id, { end_point: { lat, lon } });
				mapMode.set('idle');
				if (wizardStep === 2) { wizardStep = 3; mapMode.set('add-waypoint'); }
			} else if (mode === 'add-waypoint') {
				const name = wizardStep === 3
					? (wizardWpName.trim() || `WP ${(selected.waypoints.length + 1)}`)
					: (newWpForm.name || prompt('Wegpunktname:') || `WP ${(selected.waypoints.length + 1)}`);
				await convoysApi.createWaypoint(selected.id, {
					name,
					type: wizardStep === 3 ? 'waypoint' : newWpForm.type,
					lat,
					lon,
					hold_duration_min: wizardStep === 3 ? 0 : newWpForm.hold_duration_min,
					halt_purpose: wizardStep === 3 ? undefined : (newWpForm.halt_purpose || undefined),
					order_index: selected.waypoints.length,
				});
				wizardWpName = '';
				if (wizardStep !== 3) mapMode.set('idle');
			}
			await refreshConvoy();
		} catch (e) {
			console.error('handleMapClick error:', e);
			error = e instanceof Error ? e.message : 'Fehler beim Setzen des Punkts';
		}
	}

	function handleMapMove(lat: number, lon: number) {
		mapCenter = [lat, lon];
	}

	function wizardSetPoint(lat: number, lon: number, _label: string) {
		handleMapClick(lat, lon);
	}

	function wizardSkip() {
		if (wizardStep === 1) { wizardStep = 2; mapMode.set('set-end'); }
		else if (wizardStep === 2) { wizardStep = 3; mapMode.set('add-waypoint'); }
		else if (wizardStep === 3) { wizardStep = 0; mapMode.set('idle'); }
	}

	function wizardFinish() {
		wizardStep = 0;
		mapMode.set('idle');
	}

	// ── Waypoint ────────────────────────────────────────────────────
	async function deleteWaypoint(wpId: string) {
		if (!selected) return;
		await convoysApi.deleteWaypoint(selected.id, wpId);
		await refreshConvoy();
	}

	// ── Route ────────────────────────────────────────────────────────
	async function calculateRoute() {
		if (!selected) return;
		loading = true; error = '';
		try {
			const r = await convoysApi.calculateRoute(selected.id);
			route = { geojson: r.geojson, distance_m: r.distance_m, duration_s: r.duration_s, fuel_analysis: r.fuel_analysis };
			fuelStations = [];
			showFuelStations = false;
			activeRoute.set(r);
			await refreshConvoy();
			activeTab = 'zeitplan';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Routing fehlgeschlagen';
		} finally { loading = false; }
	}

	// ── Fuel stations ────────────────────────────────────────────────
	async function searchFuelStations() {
		if (!selected || !route?.fuel_analysis?.fuel_stop_position) return;
		fuelStationsLoading = true;
		showFuelStations = false;
		try {
			const { lat, lon } = route.fuel_analysis.fuel_stop_position;
			fuelStations = await convoysApi.findFuelStations(selected.id, lat, lon, 5000);
			showFuelStations = true;
		} catch { error = 'Tankstellensuche fehlgeschlagen'; }
		finally { fuelStationsLoading = false; }
	}

	async function addFuelStopWaypoint(station: FuelStation) {
		if (!selected || !route?.fuel_analysis) return;
		const stopKm = route.fuel_analysis.fuel_stop_km ?? 0;
		await convoysApi.createWaypoint(selected.id, {
			name: station.name,
			type: 'technical_stop',
			halt_purpose: 'fuel',
			lat: station.lat,
			lon: station.lon,
			hold_duration_min: 25,
			order_index: selected.waypoints.length,
			notes: `Tankstopp bei km ${stopKm} – ${station.brand ?? station.name}${station.opening_hours ? ' · ' + station.opening_hours : ''}`,
		});
		showFuelStations = false;
		fuelStations = [];
		await refreshConvoy();
		// Trigger new route calculation
		await calculateRoute();
	}

	// ── Closures ─────────────────────────────────────────────────────
	async function toggleClosures() {
		if (closures && showClosures) { showClosures = false; return; }
		showClosures = false;
		try {
			const [lat, lon] = mapCenter;
			closures = await overpassApi.getClosures(lat, lon) as FeatureCollection;
			showClosures = true;
		} catch { error = 'Sperrungsdaten nicht verfügbar'; }
	}

	// ── Helpers ─────────────────────────────────────────────────────
	function formatDuration(s: number | null) {
		if (!s) return '–';
		const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
		return h > 0 ? `${h} h ${m} min` : `${m} min`;
	}
	function formatTime(iso: string | null) {
		if (!iso) return '–';
		return new Date(iso).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
	}
	function logout() { auth.logout(); goto('/login'); }

	let assignedIds = $derived(new Set(selected?.convoy_vehicles.map(cv => cv.vehicle.id) ?? []));
	const apiBase = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

	const WP_TYPE_LABELS: Record<string, string> = {
		waypoint: 'Wegpunkt', stop: 'Halt',
		checkpoint: 'Kontrollpunkt', technical_stop: 'Techn. Halt',
	};
	const STATUS_LABELS: Record<string, string> = {
		planned: 'Geplant', en_route: 'Unterwegs',
		arrived: 'Angekommen', delayed: 'Verspätung',
	};
	const STATUS_COLORS: Record<string, string> = {
		planned: '#95a5a6', en_route: '#3498db',
		arrived: '#27ae60', delayed: '#e74c3c',
	};
</script>

<div class="app">
	<!-- ── Mobile top bar (hidden on desktop via CSS) ── -->
	<div class="topbar">
		<button class="hamburger" onclick={() => (sidebarOpen = !sidebarOpen)} aria-expanded={sidebarOpen} aria-controls="sidebar" aria-label="Menü">☰</button>
		<span class="topbar-name">{selected?.name ?? 'MarschPlan'}</span>
		<div class="topbar-actions">
			<button class="btn-map" class:active={$mapMode === 'set-start'} onclick={() => mapMode.set($mapMode === 'set-start' ? 'idle' : 'set-start')} aria-label="Startpunkt setzen">📍</button>
			<button class="btn-map" class:active={$mapMode === 'set-end'} onclick={() => mapMode.set($mapMode === 'set-end' ? 'idle' : 'set-end')} aria-label="Zielpunkt setzen">🏁</button>
			<button class="btn-map" class:active={$mapMode === 'add-waypoint'} onclick={() => mapMode.set($mapMode === 'add-waypoint' ? 'idle' : 'add-waypoint')} aria-label="Wegpunkt hinzufügen">➕</button>
		</div>
	</div>

	<!-- ── Sidebar backdrop (mobile only, shown when sidebar is open) ── -->
	{#if sidebarOpen}
		<button class="sidebar-backdrop" onclick={() => (sidebarOpen = false)} aria-label="Menü schließen"></button>
	{/if}

	<!-- ── Sidebar ──────────────────────────────────────────────────── -->
	<aside id="sidebar" class="sidebar" class:open={sidebarOpen}>
		<div class="sidebar-header">
			<span class="logo">MarschPlan</span>
			<button class="logout-btn" onclick={logout} title="Abmelden">✕</button>
		</div>

		<!-- Convoy-Selektor -->
		<div class="convoy-selector">
			<select onchange={(e) => { const c = convoyList.find(x => x.id === (e.target as HTMLSelectElement).value); if (c) selectConvoy(c); }}>
				{#if convoyList.length === 0}<option value="">Kein Marschverband</option>{/if}
				{#each convoyList as c}
					<option value={c.id} selected={selected?.id === c.id}>
						{c.parent_convoy_id ? '  ↳ ' : ''}{c.name}
					</option>
				{/each}
			</select>
			<button class="btn-small" onclick={() => (showConvoyForm = true)}>+ Neu</button>
		</div>

		{#if error}
			<div class="error-bar">
				<span>{error}</span>
				<button onclick={() => (error = '')}>✕</button>
			</div>
		{/if}

		{#if wizardStep === 0}
			<!-- Tabs -->
			<div class="tabs">
				{#each [['convoy','Plan'],['fahrzeuge','Fahrzeuge'],['wegpunkte','Wegpunkte'],['zeitplan','Zeitplan'],['export','Export'],['lage','Lage'],['org','Org']] as [tab, label]}
					<button class="tab" class:active={activeTab === tab} onclick={() => (activeTab = tab as typeof activeTab)}>{label}</button>
				{/each}
			</div>

			<div class="tab-content">

				<!-- ── TAB: Plan ── -->
				{#if activeTab === 'convoy' && selected}
					<div class="section">
						<p><strong>Organisation:</strong> {selected.organization ?? '–'}</p>
						<p><strong>Startzeit:</strong> {selected.start_time ? new Date(selected.start_time).toLocaleString('de-DE') : '–'}</p>
						<p><strong>Tempo:</strong> {selected.speed_urban_kmh} km/h (innerorts) / {selected.speed_rural_kmh} km/h (außerorts) · {{ schnell: 'Autobahn', bundesstrasse: 'Bundesstr.', landstrasse: 'Landstr.' }[selected.road_preference] ?? selected.road_preference}</p>
						<p><strong>Abstände:</strong> {selected.spacing_urban_m} m / {selected.spacing_rural_m} m / {selected.spacing_motorway_m} m (i/a/BAB)</p>
						{#if selected.marschform}<p><strong>Marschform:</strong> {({ geschlossener_verband:'Geschlossener Verband', einzelgruppen:'Einzelgruppen', individuell:'Individuelle Anreise' })[selected.marschform] ?? selected.marschform}</p>{/if}
						{#if selected.ablaufpunkt}<p><strong>Ablaufpunkt:</strong> {selected.ablaufpunkt}</p>{/if}
						{#if selected.ablaufführer}<p><strong>Ablaufführer:</strong> {selected.ablaufführer}</p>{/if}
						{#if selected.funkgruppe}<p><strong>Funkgruppe:</strong> {selected.funkgruppe}</p>{/if}
						{#if selected.lage}<details><summary><strong>Lage</strong></summary><p class="detail-text">{selected.lage}</p></details>{/if}
						{#if selected.auftrag}<details><summary><strong>Auftrag</strong></summary><p class="detail-text">{selected.auftrag}</p></details>{/if}
						{#if selected.parent_convoy_id}
							<p class="tag-pill">Teilverband</p>
						{/if}
					</div>
					<div class="map-actions">
						<button class="btn-map" class:active={$mapMode === 'set-start'} onclick={() => mapMode.set($mapMode === 'set-start' ? 'idle' : 'set-start')}>📍 Start</button>
						<button class="btn-map" class:active={$mapMode === 'set-end'} onclick={() => mapMode.set($mapMode === 'set-end' ? 'idle' : 'set-end')}>🏁 Ziel</button>
						<button class="btn-map" class:active={$mapMode === 'add-waypoint'} onclick={() => mapMode.set($mapMode === 'add-waypoint' ? 'idle' : 'add-waypoint')}>➕ Wegpunkt</button>
					</div>
					{#if $mapMode === 'add-waypoint'}
						<div class="wp-quick-form">
							<input placeholder="Name" bind:value={newWpForm.name} />
							<select bind:value={newWpForm.type}>
								<option value="waypoint">Wegpunkt</option>
								<option value="stop">Halt</option>
								<option value="checkpoint">Kontrollpunkt</option>
								<option value="technical_stop">Techn. Halt</option>
							</select>
							{#if newWpForm.type === 'technical_stop'}
								<select bind:value={newWpForm.halt_purpose}>
									<option value="">Grund wählen…</option>
									<option value="fuel">Tanken</option>
									<option value="rest">Pause</option>
									<option value="maintenance">Wartung</option>
									<option value="other">Sonstiges</option>
								</select>
							{/if}
							<input type="number" placeholder="Haltezeit (min)" bind:value={newWpForm.hold_duration_min} min="0" />
							<p class="hint">Jetzt auf Karte klicken ↗</p>
						</div>
					{/if}
					<div class="route-actions">
						<button class="btn-primary" onclick={calculateRoute} disabled={loading}>
							{loading ? 'Berechne…' : '🗺 Route berechnen'}
						</button>
						{#if route}
							<p class="route-info">{((route.distance_m ?? 0) / 1000).toFixed(1)} km · {formatDuration(route.duration_s)}</p>
							{#if route.fuel_analysis?.fuel_stop_needed}
								<div class="fuel-warning">
									<p>⛽ <strong>Tankstopp nötig!</strong></p>
									<p class="fuel-detail">
										{route.fuel_analysis.limiting_vehicle} hat nur <strong>{route.fuel_analysis.min_range_km} km</strong> Reichweite
										(Route: {route.fuel_analysis.route_distance_km} km).
										Empfohlener Stopp bei km {route.fuel_analysis.fuel_stop_km}.
									</p>
									<button class="btn-fuel-search" onclick={searchFuelStations} disabled={fuelStationsLoading}>
										{fuelStationsLoading ? 'Suche…' : '🔍 Tankstellen suchen'}
									</button>
									{#if showFuelStations && fuelStations.length}
										<ul class="fuel-station-list">
											{#each fuelStations as s}
												<li class="fuel-station-item">
													<div>
														<strong>{s.name}</strong>
														{#if s.brand && s.brand !== s.name}<span class="tag">{s.brand}</span>{/if}
														<span class="tag">{(s.distance_m / 1000).toFixed(1)} km vom Stopp</span>
														{#if s.opening_hours}<span class="tag">{s.opening_hours}</span>{/if}
													</div>
													<button class="btn-small" onclick={() => addFuelStopWaypoint(s)}>+ Waypoint</button>
												</li>
											{/each}
										</ul>
									{:else if showFuelStations}
										<p class="hint">Keine Tankstellen in der Nähe gefunden. Radius erhöhen?</p>
									{/if}
								</div>
							{:else if route.fuel_analysis?.min_range_km}
								<p class="fuel-ok">✅ Reichweite ausreichend ({route.fuel_analysis.min_range_km} km / {route.fuel_analysis.route_distance_km} km)</p>
							{/if}
						{/if}
					</div>

					<!-- V2: Teilverband -->
					<div class="section" style="margin-top:.75rem">
						<div class="section-header">
							<strong>Teilverbände</strong>
							<button class="btn-small" onclick={() => (showSubConvoyForm = !showSubConvoyForm)}>+ Neu</button>
						</div>
						{#if showSubConvoyForm}
							<form class="inline-form" onsubmit={async (e) => {
								e.preventDefault();
								if (!selected) return;
								await convoysApi.createSubConvoy(selected.id, { name: newConvoy.name, speed_urban_kmh: 40, speed_rural_kmh: 65 });
								await loadData();
								showSubConvoyForm = false;
								newConvoy = { ...newConvoy, name: '' };
							}}>
								<input placeholder="Name des Teilverbands *" bind:value={newConvoy.name} required />
								<button type="submit">Erstellen</button>
							</form>
						{/if}
						{#each convoyList.filter(c => c.parent_convoy_id === selected?.id) as sub}
							<div class="sub-convoy-item" onclick={() => selectConvoy(sub)}>
								↳ {sub.name}
							</div>
						{/each}
					</div>
				{/if}

				<!-- ── TAB: Fahrzeuge ── -->
				{#if activeTab === 'fahrzeuge'}
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
								<hr style="border-color:rgba(255,255,255,.15);margin:.2rem 0" />
								<input placeholder="Tankvolumen (Liter)" type="number" step="0.1" min="0" bind:value={newVehicle.tank_capacity_l} />
								<input placeholder="Verbrauch (l/100 km)" type="number" step="0.1" min="0" bind:value={newVehicle.fuel_consumption_l100km} />
								<input placeholder="Aktueller Füllstand (Liter)" type="number" step="0.1" min="0" bind:value={newVehicle.current_fuel_l} />
								<button type="submit">Speichern</button>
							</form>
						{/if}
						<ul class="vehicle-list">
							{#each allVehicles as v}
								<li class="vehicle-item" style="flex-direction:column;align-items:stretch;gap:.3rem">
									<div style="display:flex;justify-content:space-between;align-items:center">
										<div>
											<strong>{v.name}</strong>
											{#if v.callsign}<span class="tag">{v.callsign}</span>{/if}
											{#if v.license_plate}<span class="tag">{v.license_plate}</span>{/if}
											{#if v.range_km}<span class="tag fuel-tag">⛽ {v.range_km} km</span>{/if}
										</div>
										{#if selected}
											{#if assignedIds.has(v.id)}
												<button class="btn-small danger" onclick={() => removeVehicleFromConvoy(v.id)}>–</button>
											{:else}
												<button class="btn-small" onclick={() => addVehicleToConvoy(v.id)}>+</button>
											{/if}
										{/if}
									</div>
									{#if selected && !assignedIds.has(v.id)}
										<select class="sf-select" bind:value={vehicleSonderfunktion[v.id]}>
											<option value="">Sonderfunktion…</option>
											<option value="spitzenführer">Spitzenführer</option>
											<option value="schließender">Schließender (Ablaufführer)</option>
											<option value="sanitaet">Sanitätsdienstliche Absicherung</option>
											<option value="führungsfahrzeug">Führungsfahrzeug</option>
										</select>
									{/if}
								</li>
							{/each}
						</ul>
						{#if selected?.convoy_vehicles.length}
							<div class="section-header" style="margin-top:.75rem"><strong>Im Verband (Marschfolge)</strong></div>
							<ol class="vehicle-list">
								{#each selected.convoy_vehicles as cv}
									<li class="vehicle-item convoy-vehicle-row">
										<div class="veh-left">
											<span class="veh-pos">{cv.position + 1}.</span>
											<div>
												<span>{cv.vehicle.name}</span>
												{#if cv.vehicle.callsign}<span class="tag">{cv.vehicle.callsign}</span>{/if}
												{#if cv.sonderfunktion}
													<span class="tag sonder">{({ spitzenführer:'Spitze', schließender:'Schließ.', sanitaet:'San.', ablaufführer:'Ablauf', führungsfahrzeug:'Führung' })[cv.sonderfunktion] ?? cv.sonderfunktion}</span>
												{/if}
											</div>
										</div>
										<span class="status-dot" style="background:{STATUS_COLORS[cv.vehicle_status] ?? '#95a5a6'}" title={STATUS_LABELS[cv.vehicle_status] ?? cv.vehicle_status}></span>
									</li>
								{/each}
							</ol>
							<p class="hint" style="margin-top:.4rem">Position 1 = Spitzenführer, letztes Fahrzeug = Schließender</p>
						{/if}
					</div>
				{/if}

				<!-- ── TAB: Wegpunkte ── -->
				{#if activeTab === 'wegpunkte' && selected}
					<div class="section">
						<div class="section-header">
							<strong>Wegpunkte</strong>
							<button class="btn-small" class:active={$mapMode === 'add-waypoint'} onclick={() => mapMode.set($mapMode === 'add-waypoint' ? 'idle' : 'add-waypoint')}>
								+ Karte
							</button>
						</div>
						{#if !selected.waypoints.length}
							<p class="hint">Noch keine Wegpunkte.</p>
						{/if}
						<ul class="wp-list">
							{#each selected.waypoints as wp}
								<li class="wp-item">
									<div>
										<strong>{wp.name}</strong>
										<span class="tag">{WP_TYPE_LABELS[wp.type] ?? wp.type}</span>
										{#if wp.halt_purpose}<span class="tag orange">{wp.halt_purpose}</span>{/if}
										{#if wp.hold_duration_min > 0}<span class="tag">{wp.hold_duration_min} min</span>{/if}
									</div>
									<button class="btn-small danger" onclick={() => deleteWaypoint(wp.id)}>✕</button>
								</li>
							{/each}
						</ul>
					</div>
				{/if}

				<!-- ── TAB: Zeitplan ── -->
				{#if activeTab === 'zeitplan' && selected}
					<div class="section">
						<strong>Zeitplan</strong>
						{#if selected.waypoints.some(w => w.planned_arrival)}
							<table class="schedule-table">
								<thead><tr><th>Wegpunkt</th><th>Ankunft</th><th>Abfahrt</th></tr></thead>
								<tbody>
									{#each selected.waypoints as wp}
										<tr>
											<td>{wp.name} {#if wp.type === 'technical_stop'}<span class="tag orange">Techn.</span>{/if}</td>
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

				<!-- ── TAB: Export ── -->
				{#if activeTab === 'export' && selected}
					<div class="section">
						<strong>Exportieren</strong>
						<div class="export-grid">
							<a class="btn-export" href="{apiBase}/api/convoys/{selected.id}/export/gpx" target="_blank">
								📍 GPX herunterladen
							</a>
							<a class="btn-export" href="{apiBase}/api/convoys/{selected.id}/export/json" target="_blank">
								📄 JSON herunterladen
							</a>
							<a class="btn-export" href="{apiBase}/api/convoys/{selected.id}/export/pdf" target="_blank">
								🖨 Marschbefehl PDF
							</a>
							<button class="btn-export" onclick={() => navigator.clipboard.writeText(`${window.location.origin}/share/${selected?.share_token}`)}>
								🔗 Link kopieren
							</button>
						</div>
						<div class="section-header" style="margin-top:1rem"><strong>Live-Tracking</strong></div>
						<a class="btn-export" href="/tracking/{selected.id}" target="_blank">🔴 Tracking-Ansicht öffnen</a>
						<div class="section-header" style="margin-top:1rem"><strong>Sperrungen & Baustellen</strong></div>
						<button class="btn-export" class:active={showClosures} onclick={toggleClosures}>
							{showClosures ? '🚧 Sperrungen ausblenden' : '🚧 Sperrungen laden'}
						</button>
					</div>
				{/if}

				<!-- ── TAB: Lage ── -->
				{#if activeTab === 'lage' && selected}
					<LageLayerPanel
						convoyId={selected.id}
						onLayersChange={(layers) => lageLayers.set(layers)}
					/>
				{/if}

				<!-- ── TAB: Org ── -->
				{#if activeTab === 'org'}
					<div class="section">
						<div class="section-header">
							<strong>Organisationen</strong>
							<button class="btn-small" onclick={async () => {
								const name = prompt('Organisationsname:');
								if (name) { await orgsApi.create(name); organizations = await orgsApi.list(); }
							}}>+ Neu</button>
						</div>
						{#each organizations as org}
							<div class="org-item">
								<div>
									<strong>{org.name}</strong>
									<span class="tag">{org.my_role}</span>
									<span class="tag">{org.member_count} Mitglieder</span>
								</div>
								{#if org.my_role === 'admin'}
									<button class="btn-small" onclick={async () => {
										const email = prompt('E-Mail des neuen Mitglieds:');
										const role = prompt('Rolle (admin/planer/fahrer/beobachter):', 'beobachter');
										if (email && role) { await orgsApi.addMember(org.id, email, role); organizations = await orgsApi.list(); }
									}}>+ Mitglied</button>
								{/if}
							</div>
						{/each}
						{#if !organizations.length}
							<p class="hint">Noch keine Organisationen erstellt.</p>
						{/if}
					</div>
				{/if}
			</div>
		{:else}
			<!-- Wizard -->
			<div class="wizard">
				<div class="wizard-steps">
					<span class:active={wizardStep === 1}>1</span>
					<span class="sep">›</span>
					<span class:active={wizardStep === 2}>2</span>
					<span class="sep">›</span>
					<span class:active={wizardStep === 3}>3</span>
				</div>

				{#if wizardStep === 1}
					<h3 class="wizard-title">Startpunkt setzen</h3>
					<LocationSearch
						placeholder="Startort suchen…"
						onSelect={wizardSetPoint}
					/>
					<p class="hint">oder direkt auf die Karte klicken ↗</p>
					<button class="btn-skip" onclick={wizardSkip}>Überspringen →</button>

				{:else if wizardStep === 2}
					<h3 class="wizard-title">Zielpunkt setzen</h3>
					<LocationSearch
						placeholder="Zielort suchen…"
						onSelect={wizardSetPoint}
					/>
					<p class="hint">oder direkt auf die Karte klicken ↗</p>
					<button class="btn-skip" onclick={wizardSkip}>Überspringen →</button>

				{:else if wizardStep === 3}
					<h3 class="wizard-title">Wegpunkte hinzufügen</h3>
					<input
						class="wp-name-input"
						placeholder="Name (optional)"
						bind:value={wizardWpName}
					/>
					<LocationSearch
						placeholder="Wegpunkt suchen…"
						onSelect={wizardSetPoint}
					/>
					<p class="hint">oder auf die Karte klicken ↗</p>
					{#if selected?.waypoints?.length}
						<ul class="wizard-wp-list">
							{#each selected.waypoints as wp}
								<li>📍 {wp.name}</li>
							{/each}
						</ul>
					{/if}
					<button class="btn-primary" onclick={wizardFinish}>Fertig ✓</button>
					<button class="btn-skip" onclick={wizardSkip}>Überspringen →</button>
				{/if}
			</div>
		{/if}
	</aside>

	<!-- ── Karte ─────────────────────────────────────────────────────── -->
	<main class="map-area">
		<!-- FAB route button shown on mobile only -->
		<button class="fab-route" onclick={calculateRoute} disabled={loading}>
			{loading ? 'Berechne…' : '🗺 Route'}
		</button>
		{#if $mapMode !== 'idle'}
			<div class="map-hint-bar">
				{#if $mapMode === 'set-start'}Start setzen – auf Karte klicken{/if}
				{#if $mapMode === 'set-end'}Ziel setzen – auf Karte klicken{/if}
				{#if $mapMode === 'add-waypoint'}Wegpunkt setzen – auf Karte klicken{/if}
				<button onclick={() => mapMode.set('idle')}>Abbrechen</button>
			</div>
		{/if}

		<!-- V3: Wetter-Widget -->
		<WeatherWidget lat={mapCenter[0]} lon={mapCenter[1]} />

		<!-- V3: Lage-Layer-Panel (floating) -->
		{#if selected && $lageLayers.length > 0}
			<div class="lage-floating">
				<LageLayerPanel convoyId={selected.id} onLayersChange={(layers) => lageLayers.set(layers)} />
			</div>
		{/if}

		<ServiceStatus />

		<MapView
			startPoint={selected?.start_point}
			endPoint={selected?.end_point}
			waypoints={selected?.waypoints ?? []}
			routeGeojson={route?.geojson as never}
			lageLayers={$lageLayers}
			closuresGeojson={showClosures ? closures : null}
			onMapClick={handleMapClick}
			onMapMove={handleMapMove}
		/>
	</main>
</div>

<!-- ── Modal: Neuer Marschverband ─────────────────────────────────── -->
{#if showConvoyForm}
	<div class="modal-backdrop" onclick={() => (showConvoyForm = false)}>
		<div class="modal" onclick={(e) => e.stopPropagation()}>
			<h2>Neuer Marschverband</h2>
			<form onsubmit={(e) => { e.preventDefault(); createConvoy(); }}>
				<label>Name *<input bind:value={newConvoy.name} required placeholder="z.B. KatS-Verband Bayern 1" /></label>
				<label>Startzeit (optional)<input type="datetime-local" bind:value={newConvoy.start_time} /></label>
				<label>Geschw. innerorts (km/h)<input type="number" bind:value={newConvoy.speed_urban_kmh} min="10" max="60" /></label>
				<label>Geschw. außerorts (km/h)<input type="number" bind:value={newConvoy.speed_rural_kmh} min="30" max="100" /></label>
				<label>Straßenpräferenz
					<select bind:value={newConvoy.road_preference}>
						<option value="schnell">Schnellste Route (Autobahn erlaubt)</option>
						<option value="bundesstrasse">Bundesstraßen bevorzugt</option>
						<option value="landstrasse">Nur Landstraßen</option>
					</select>
				</label>
				<label>Fahrzeugabstand Innerorts (m)<input type="number" bind:value={newConvoy.spacing_urban_m} min="5" max="200" /></label>
				<label>Fahrzeugabstand Außerorts (m)<input type="number" bind:value={newConvoy.spacing_rural_m} min="10" max="500" /></label>
				<label>Fahrzeugabstand Autobahn (m)<input type="number" bind:value={newConvoy.spacing_motorway_m} min="10" max="500" /></label>
				<p class="hint" style="margin:.25rem 0">Weitere Felder (Lage, Auftrag, Funkgruppe…) kannst du nach dem Erstellen im Plan-Tab ergänzen.</p>
				<div class="modal-actions">
					<button type="button" onclick={() => (showConvoyForm = false)}>Abbrechen</button>
					<button type="submit" class="btn-primary">Erstellen & Punkte setzen →</button>
				</div>
			</form>
		</div>
	</div>
{/if}

<style>
	:global(body) { margin: 0; font-family: system-ui, sans-serif; }
	.app { display: flex; height: 100vh; overflow: hidden; }

	.sidebar { width: 340px; min-width: 280px; background: #1a2744; color: white; display: flex; flex-direction: column; overflow: hidden; }
	.sidebar-header { display: flex; justify-content: space-between; align-items: center; padding: 1rem; border-bottom: 1px solid rgba(255,255,255,.15); }
	.logo { font-size: 1.1rem; font-weight: 700; }
	.logout-btn { background: none; border: none; color: rgba(255,255,255,.6); cursor: pointer; font-size: 1rem; }

	.convoy-selector { display: flex; gap: .5rem; padding: .75rem 1rem; border-bottom: 1px solid rgba(255,255,255,.1); }
	.convoy-selector select { flex: 1; padding: .4rem; border-radius: 4px; border: none; background: rgba(255,255,255,.12); color: white; }

	.tabs { display: flex; flex-wrap: wrap; border-bottom: 1px solid rgba(255,255,255,.1); }
	.tab { flex: 1; min-width: 48px; padding: .5rem .2rem; background: none; border: none; color: rgba(255,255,255,.6); font-size: .72rem; cursor: pointer; border-bottom: 2px solid transparent; }
	.tab.active { color: white; border-bottom-color: #e74c3c; }

	.tab-content { flex: 1; overflow-y: auto; padding: .75rem 1rem; }

	.section { margin-bottom: .75rem; }
	.section p { margin: .3rem 0; font-size: .85rem; color: rgba(255,255,255,.85); }
	.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: .4rem; font-size: .85rem; }

	.map-actions { display: flex; flex-wrap: wrap; gap: .4rem; margin-bottom: .5rem; }
	.btn-map { padding: .35rem .55rem; background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.2); color: white; border-radius: 4px; font-size: .78rem; cursor: pointer; }
	.btn-map.active { background: #e74c3c; border-color: #e74c3c; }

	.btn-primary { width: 100%; padding: .6rem; background: #e74c3c; color: white; border: none; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: .9rem; }
	.btn-primary:disabled { opacity: .5; cursor: not-allowed; }

	.btn-small { padding: .22rem .45rem; background: rgba(255,255,255,.15); border: 1px solid rgba(255,255,255,.25); color: white; border-radius: 4px; font-size: .75rem; cursor: pointer; }
	.btn-small.danger { background: rgba(231,76,60,.3); border-color: #e74c3c; }
	.btn-small.active { background: #e74c3c; }

	.export-grid { display: flex; flex-direction: column; gap: .4rem; margin-top: .4rem; }
	.btn-export { display: block; padding: .45rem .75rem; background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.2); color: white; border-radius: 4px; font-size: .82rem; text-decoration: none; cursor: pointer; text-align: left; }
	.btn-export.active { background: rgba(231,76,60,.3); border-color: #e74c3c; }

	.route-actions { margin-top: .75rem; }
	.route-info { font-size: .85rem; color: rgba(255,255,255,.8); margin: .4rem 0; }

	.hint { font-size: .78rem; color: rgba(255,255,255,.45); font-style: italic; margin: .25rem 0; }

	.vehicle-list { list-style: none; padding: 0; margin: 0; }
	.vehicle-item { display: flex; justify-content: space-between; align-items: center; padding: .35rem 0; border-bottom: 1px solid rgba(255,255,255,.08); font-size: .83rem; }
	.status-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }

	.tag { display: inline-block; padding: .1rem .3rem; background: rgba(255,255,255,.15); border-radius: 3px; font-size: .7rem; margin-left: .2rem; }
	.tag.orange { background: rgba(230,126,34,.4); }

	.wp-list { list-style: none; padding: 0; margin: 0; }
	.wp-item { display: flex; justify-content: space-between; align-items: center; padding: .35rem 0; border-bottom: 1px solid rgba(255,255,255,.08); font-size: .83rem; }

	.wp-quick-form { background: rgba(255,255,255,.07); border-radius: 4px; padding: .5rem; margin-bottom: .5rem; display: flex; flex-direction: column; gap: .35rem; }
	.wp-quick-form input, .wp-quick-form select { padding: .3rem .4rem; border: none; border-radius: 3px; background: rgba(255,255,255,.12); color: white; font-size: .82rem; }

	.schedule-table { width: 100%; border-collapse: collapse; font-size: .8rem; }
	.schedule-table th, .schedule-table td { padding: .3rem .4rem; text-align: left; border-bottom: 1px solid rgba(255,255,255,.1); }
	.schedule-table th { color: rgba(255,255,255,.6); font-weight: 600; }

	.inline-form { display: flex; flex-direction: column; gap: .35rem; margin-bottom: .5rem; }
	.inline-form input, .inline-form select { padding: .35rem .4rem; border-radius: 4px; border: none; background: rgba(255,255,255,.12); color: white; font-size: .83rem; }
	.inline-form input::placeholder { color: rgba(255,255,255,.4); }
	.inline-form button { padding: .35rem; background: #27ae60; color: white; border: none; border-radius: 4px; cursor: pointer; }

	.sub-convoy-item { padding: .3rem .4rem; background: rgba(255,255,255,.07); border-radius: 4px; margin-bottom: .25rem; font-size: .82rem; cursor: pointer; }
	.sub-convoy-item:hover { background: rgba(255,255,255,.12); }

	.org-item { display: flex; justify-content: space-between; align-items: center; padding: .35rem 0; border-bottom: 1px solid rgba(255,255,255,.08); font-size: .83rem; }

	.tag-pill { display: inline-block; background: rgba(52,152,219,.3); border: 1px solid #3498db; border-radius: 12px; padding: .1rem .5rem; font-size: .72rem; color: #74b9ff; }

	.error-bar { background: #c0392b; color: white; padding: .4rem .75rem; font-size: .8rem; margin: 0; display: flex; justify-content: space-between; align-items: flex-start; gap: .5rem; flex-shrink: 0; word-break: break-word; }
	.error-bar button { background: none; border: none; color: white; cursor: pointer; font-size: 1rem; flex-shrink: 0; line-height: 1; padding: 0; }

	.map-area { flex: 1; position: relative; }
	/* Desktop defaults — these elements exist in DOM but are hidden */
	.topbar { display: none; }
	.sidebar-backdrop { display: none; }
	.fab-route { display: none; }
	.map-hint-bar { position: absolute; top: 1rem; left: 50%; transform: translateX(-50%); z-index: 10; background: rgba(26,39,68,.9); color: white; padding: .5rem 1rem; border-radius: 20px; display: flex; align-items: center; gap: 1rem; font-size: .85rem; }
	.map-hint-bar button { background: rgba(255,255,255,.2); border: none; color: white; border-radius: 12px; padding: .2rem .6rem; cursor: pointer; }

	.lage-floating { position: absolute; bottom: 2rem; right: 1rem; z-index: 10; }

	/* Modal */
	.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.5); display: flex; align-items: center; justify-content: center; z-index: 100; }
	.modal { background: white; border-radius: 8px; padding: 2rem; width: 100%; max-width: 420px; color: #333; }
	.modal h2 { margin: 0 0 1.25rem; }
	.modal label { display: flex; flex-direction: column; gap: .25rem; margin-bottom: .75rem; font-size: .85rem; font-weight: 600; }
	.modal input, .modal select { padding: .5rem; border: 1px solid #ccc; border-radius: 4px; font-size: 1rem; }
	.modal-actions { display: flex; justify-content: flex-end; gap: .5rem; margin-top: 1rem; }
	.modal-actions button { padding: .5rem 1rem; border-radius: 4px; cursor: pointer; border: 1px solid #ccc; }
	.modal-actions .btn-primary { background: #1a2744; color: white; border-color: #1a2744; }
	.modal { max-height: 90vh; overflow-y: auto; }
	.modal label textarea { padding: .5rem; border: 1px solid #ccc; border-radius: 4px; font-size: .9rem; resize: vertical; }
	.modal label small { font-weight: 400; color: #888; font-size: .78rem; }

	.convoy-vehicle-row { flex-direction: row; gap: .4rem; }
	.veh-left { display: flex; align-items: center; gap: .35rem; flex: 1; min-width: 0; }
	.veh-pos { font-size: .75rem; color: rgba(255,255,255,.5); flex-shrink: 0; }
	.tag.sonder { background: rgba(52,152,219,.4); color: #aed6f1; }

	.sf-select { width: 100%; padding: .25rem .35rem; border-radius: 3px; border: none; background: rgba(255,255,255,.08); color: rgba(255,255,255,.7); font-size: .72rem; }

	.detail-text { font-size: .82rem; color: rgba(255,255,255,.8); margin: .25rem 0 0; white-space: pre-wrap; }
	details summary { cursor: pointer; font-size: .82rem; color: rgba(255,255,255,.75); }

	.tag.fuel-tag { background: rgba(39,174,96,.35); color: #a9dfbf; }

	.fuel-warning { background: rgba(231,76,60,.15); border: 1px solid rgba(231,76,60,.5); border-radius: 6px; padding: .6rem; margin-top: .5rem; }
	.fuel-warning p { margin: .2rem 0; font-size: .83rem; }
	.fuel-detail { color: rgba(255,255,255,.8); }
	.btn-fuel-search { width: 100%; margin-top: .4rem; padding: .4rem; background: #e67e22; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: .82rem; font-weight: 600; }
	.btn-fuel-search:disabled { opacity: .5; cursor: not-allowed; }

	.fuel-station-list { list-style: none; padding: 0; margin: .4rem 0 0; display: flex; flex-direction: column; gap: .3rem; }
	.fuel-station-item { display: flex; justify-content: space-between; align-items: flex-start; gap: .4rem; padding: .35rem; background: rgba(255,255,255,.07); border-radius: 4px; font-size: .8rem; }

	.fuel-ok { font-size: .8rem; color: #a9dfbf; margin: .3rem 0 0; }

	.wizard { flex: 1; overflow-y: auto; padding: .75rem 1rem; display: flex; flex-direction: column; gap: .5rem; }
	.wizard-steps { display: flex; align-items: center; gap: .3rem; font-size: .75rem; color: rgba(255,255,255,.4); margin-bottom: .25rem; }
	.wizard-steps span.active { color: white; font-weight: 700; }
	.wizard-steps .sep { color: rgba(255,255,255,.25); }
	.wizard-title { margin: 0 0 .5rem; font-size: .95rem; font-weight: 600; color: white; }
	.btn-skip { background: none; border: none; color: rgba(255,255,255,.45); font-size: .78rem; cursor: pointer; padding: .2rem 0; text-align: left; }
	.btn-skip:hover { color: rgba(255,255,255,.7); }
	.wp-name-input { width: 100%; padding: .4rem .6rem; border-radius: 4px; border: 1px solid rgba(255,255,255,.2); background: rgba(255,255,255,.08); color: white; font-size: .85rem; box-sizing: border-box; }
	.wp-name-input::placeholder { color: rgba(255,255,255,.35); }
	.wizard-wp-list { list-style: none; padding: 0; margin: 0; max-height: 120px; overflow-y: auto; }
	.wizard-wp-list li { font-size: .8rem; color: rgba(255,255,255,.75); padding: .2rem 0; border-bottom: 1px solid rgba(255,255,255,.07); }

	/* ── Mobile layout (≤ 768px) ─────────────────────────────────── */
	@media (max-width: 768px) {
		/* Show top bar, push content down */
		.topbar {
			display: flex;
			align-items: center;
			gap: .5rem;
			position: fixed;
			top: 0; left: 0; right: 0;
			height: 48px;
			padding: 0 .75rem;
			background: #1a2744;
			border-bottom: 1px solid rgba(255,255,255,.1);
			z-index: 200;
		}
		.hamburger {
			background: rgba(255,255,255,.1);
			border: none;
			color: white;
			border-radius: 6px;
			width: 34px;
			height: 34px;
			font-size: 1.1rem;
			cursor: pointer;
			flex-shrink: 0;
			display: flex;
			align-items: center;
			justify-content: center;
		}
		.topbar-name {
			flex: 1;
			font-size: .9rem;
			font-weight: 600;
			color: white;
			white-space: nowrap;
			overflow: hidden;
			text-overflow: ellipsis;
		}
		.topbar-actions {
			display: flex;
			gap: .3rem;
		}
		.topbar-actions .btn-map {
			padding: .3rem .45rem;
			font-size: .8rem;
		}

		/* Push the flex layout down to clear the fixed top bar */
		.app {
			padding-top: 48px;
			box-sizing: border-box;
		}

		/* Sidebar becomes a fixed overlay from the left */
		.sidebar {
			position: fixed;
			top: 48px;
			left: 0;
			bottom: 0;
			width: min(300px, 85vw);
			z-index: 300;
			overflow-y: auto;
			transform: translateX(-100%);
			transition: transform .25s ease;
		}
		.sidebar.open {
			transform: translateX(0);
		}

		/* Backdrop behind open sidebar */
		.sidebar-backdrop {
			display: block;
			position: fixed;
			inset: 0;
			background: rgba(0,0,0,.45);
			z-index: 299;
		}

		/* FAB route button floating over map */
		.fab-route {
			display: block;
			position: fixed;
			bottom: 1.5rem;
			right: 1rem;
			z-index: 50;
			padding: .6rem 1.1rem;
			background: #e74c3c;
			color: white;
			border: none;
			border-radius: 8px;
			font-size: .9rem;
			font-weight: 600;
			cursor: pointer;
			box-shadow: 0 2px 12px rgba(0,0,0,.3);
		}
		.fab-route:disabled {
			opacity: .55;
			cursor: not-allowed;
		}
	}
</style>
