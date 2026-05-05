<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import MapView from '$lib/components/MapView.svelte';
	import WeatherWidget from '$lib/components/WeatherWidget.svelte';
	import LageLayerPanel from '$lib/components/LageLayerPanel.svelte';
	import { auth } from '$lib/stores/auth';
	import { activeConvoy, activeRoute, convoys } from '$lib/stores/convoy';
	import { lageLayers } from '$lib/stores/lage';
	import { mapMode } from '$lib/stores/map';
	import {
		convoysApi, vehiclesApi, orgsApi, overpassApi,
		type Convoy, type Vehicle, type Organization, type LageLayer
	} from '$lib/api';
	import type { FeatureCollection } from 'geojson';

	// ── State ──────────────────────────────────────────────────────────
	let allVehicles = $state<Vehicle[]>([]);
	let convoyList = $state<Convoy[]>([]);
	let organizations = $state<Organization[]>([]);
	let selected = $state<Convoy | null>(null);
	let route = $state<{ geojson: unknown; distance_m: number | null; duration_s: number | null } | null>(null);
	let closures = $state<FeatureCollection | null>(null);
	let showClosures = $state(false);
	let mapCenter = $state<[number, number]>([10.0, 51.5]);
	let activeTab = $state<'convoy'|'fahrzeuge'|'wegpunkte'|'zeitplan'|'export'|'lage'|'org'>('convoy');
	let loading = $state(false);
	let error = $state('');

	// Forms
	let showVehicleForm = $state(false);
	let showConvoyForm = $state(false);
	let showSubConvoyForm = $state(false);
	let newVehicle = $state({ name:'', callsign:'', license_plate:'', height_cm:'', weight_kg:'', length_cm:'', convoy_role:'' });
	let newConvoy = $state({ name:'', organization:'', organization_id:'', start_time:'', speed_urban_kmh:40, speed_rural_kmh:65, lage:'', auftrag:'', marschform:'geschlossener_verband', ablaufpunkt:'', ablaufzeit:'', ablaufführer:'', versorgung:'', funkgruppe:'', anlagen:'' });
	let newWpForm = $state({ name:'', type:'waypoint', hold_duration_min:0, halt_purpose:'' });
	let pendingWpClick = $state(false);

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
				lage: newConvoy.lage || undefined,
				auftrag: newConvoy.auftrag || undefined,
				marschform: newConvoy.marschform || undefined,
				ablaufpunkt: newConvoy.ablaufpunkt || undefined,
				ablaufzeit: newConvoy.ablaufzeit || undefined,
				ablaufführer: newConvoy.ablaufführer || undefined,
				versorgung: newConvoy.versorgung || undefined,
				funkgruppe: newConvoy.funkgruppe || undefined,
				anlagen: newConvoy.anlagen || undefined,
			});
			convoyList = [...convoyList, c];
			convoys.set(convoyList);
			selectConvoy(c);
			showConvoyForm = false;
			newConvoy = { name:'', organization:'', organization_id:'', start_time:'', speed_urban_kmh:40, speed_rural_kmh:65, lage:'', auftrag:'', marschform:'geschlossener_verband', ablaufpunkt:'', ablaufzeit:'', ablaufführer:'', versorgung:'', funkgruppe:'', anlagen:'' };
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
			} as never);
			allVehicles = [...allVehicles, v];
			newVehicle = { name:'', callsign:'', license_plate:'', height_cm:'', weight_kg:'', length_cm:'', convoy_role:'' };
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
		if (!selected) return;
		const mode = $mapMode;
		if (mode === 'set-start') {
			await convoysApi.update(selected.id, { start_point: { lat, lon } });
			mapMode.set('idle');
		} else if (mode === 'set-end') {
			await convoysApi.update(selected.id, { end_point: { lat, lon } });
			mapMode.set('idle');
		} else if (mode === 'add-waypoint') {
			const name = newWpForm.name || prompt('Wegpunktname:') || `WP ${(selected.waypoints.length + 1)}`;
			await convoysApi.createWaypoint(selected.id, {
				name,
				type: newWpForm.type,
				lat,
				lon,
				hold_duration_min: newWpForm.hold_duration_min,
				halt_purpose: newWpForm.halt_purpose || undefined,
				order_index: selected.waypoints.length,
			});
			mapMode.set('idle');
		}
		await refreshConvoy();
	}

	function handleMapMove(lat: number, lon: number) {
		mapCenter = [lat, lon];
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
			route = { geojson: r.geojson, distance_m: r.distance_m, duration_s: r.duration_s };
			activeRoute.set(r);
			await refreshConvoy();
			activeTab = 'zeitplan';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Routing fehlgeschlagen';
		} finally { loading = false; }
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

	$: assignedIds = new Set(selected?.convoy_vehicles.map(cv => cv.vehicle.id) ?? []);
	$: apiBase = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

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
	<!-- ── Sidebar ──────────────────────────────────────────────────── -->
	<aside class="sidebar">
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
					<p><strong>Tempo:</strong> {selected.speed_urban_kmh} km/h (innerorts) / {selected.speed_rural_kmh} km/h (außerorts)</p>
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

		{#if error}
			<p class="error-bar" onclick={() => (error = '')}>{error} ✕</p>
		{/if}
	</aside>

	<!-- ── Karte ─────────────────────────────────────────────────────── -->
	<main class="map-area">
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

		<MapView
			startPoint={selected?.start_point}
			endPoint={selected?.end_point}
			waypoints={selected?.waypoints ?? []}
			routeGeojson={route?.geojson as never}
			lageLayers={$lageLayers}
			closuresGeojson={showClosures ? closures : null}
			{onMapClick: handleMapClick}
			{onMapMove: handleMapMove}
		/>
	</main>
</div>

<!-- ── Modal: Neuer Marschverband ─────────────────────────────────── -->
{#if showConvoyForm}
	<div class="modal-backdrop" onclick={() => (showConvoyForm = false)}>
		<div class="modal" onclick={(e) => e.stopPropagation()}>
			<h2>Neuer Marschverband</h2>
			<form onsubmit={(e) => { e.preventDefault(); createConvoy(); }}>
				<label>Name *<input bind:value={newConvoy.name} required /></label>
				<label>Organisation (Text)<input bind:value={newConvoy.organization} /></label>
				{#if organizations.length}
					<label>Organisation (aus Liste)
						<select bind:value={newConvoy.organization_id}>
							<option value="">– keine –</option>
							{#each organizations as org}
								<option value={org.id}>{org.name}</option>
							{/each}
						</select>
					</label>
				{/if}
				<label>Startzeit<input type="datetime-local" bind:value={newConvoy.start_time} /></label>
				<label>Geschw. innerorts (km/h) <small>Empf.: 30–45</small><input type="number" bind:value={newConvoy.speed_urban_kmh} min="10" max="60" /></label>
				<label>Geschw. außerorts (km/h) <small>Empf.: 60–70</small><input type="number" bind:value={newConvoy.speed_rural_kmh} min="30" max="100" /></label>
				<label>Marschform
					<select bind:value={newConvoy.marschform}>
						<option value="geschlossener_verband">Geschlossener Gesamtverband</option>
						<option value="einzelgruppen">Einzelgruppen</option>
						<option value="individuell">Individuelle Anreise</option>
					</select>
				</label>
				<label>Ablaufpunkt<input placeholder="Ort des Ablaufpunkts" bind:value={newConvoy.ablaufpunkt} /></label>
				<label>Ablaufzeit<input type="datetime-local" bind:value={newConvoy.ablaufzeit} /></label>
				<label>Ablaufführer<input placeholder="Name / Rufname" bind:value={newConvoy.ablaufführer} /></label>
				<label>Funkgruppe<input placeholder="z.B. KatS Bayern 1" bind:value={newConvoy.funkgruppe} /></label>
				<label>1. Lage (Gefahren-/Schadenslage)<textarea rows="2" placeholder="Lageschilderung…" bind:value={newConvoy.lage}></textarea></label>
				<label>2. Auftrag<textarea rows="2" placeholder="Erhaltener Auftrag, Zuteilung…" bind:value={newConvoy.auftrag}></textarea></label>
				<label>4. Versorgung<textarea rows="2" placeholder="Verpflegung, Betriebsstoff, Sanitätsdienst…" bind:value={newConvoy.versorgung}></textarea></label>
				<label>6. Anlagen<textarea rows="2" placeholder="Begleitdokumente, Karten…" bind:value={newConvoy.anlagen}></textarea></label>
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

	.error-bar { background: #c0392b; color: white; padding: .5rem 1rem; font-size: .82rem; margin: 0; cursor: pointer; }

	.map-area { flex: 1; position: relative; }
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
</style>
