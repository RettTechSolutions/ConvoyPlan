<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import MapView from '$lib/components/MapView.svelte';
	import AppLogo from '$lib/components/AppLogo.svelte';
	import { convoysApi, trackingApi, type Convoy, type VehiclePosition, type RouteResult } from '$lib/api';
	import {
		livePositions, vehicleStatuses, trackingAlerts, connectTracking, disconnectTracking,
		sendPosition, trackingActive, gpsRevoked, acknowledgeAlert, dismissAlert, acknowledgeAllAlerts,
		type VehicleStatusInfo,
	} from '$lib/stores/tracking';
	import {
		STATUS_LABELS, STATUS_COLORS, STATUS_ICONS, HALT_LEVEL_LABELS, BREAKDOWN_LEVEL_LABELS,
		statusColor, statusLabel, levelLabel, type HaltLevel, type BreakdownLevel,
	} from '$lib/tracking/status';
	import { routeCoords, estimateDelay, haversine } from '$lib/tracking/eta';

	const convoyId = $page.params.convoy_id!;

	// Radius (m) around the destination within which a vehicle auto-switches to "Angekommen".
	const ARRIVAL_RADIUS_M = 150;

	let convoy = $state<Convoy | null>(null);
	let route = $state<RouteResult | null>(null);
	let routeGeojson = $derived(route?.geojson ?? null);
	let myVehicleId = $state('');
	let transmitting = $state(false);
	let manualMode = $state(false);
	let activeTab = $state<'fahrzeuge' | 'status' | 'zeitplan'>('fahrzeuge');
	let sidebarOpen = $state(false);
	// Desktop/tablet: collapse the sidebar to a thin rail to free the map (landscape).
	let sidebarCollapsed = $state(false);
	let geoWatcher: number | null = null;
	let mapCenter = $state<[number, number]>([10.0, 51.5]);
	let error = $state('');
	let mapView = $state<ReturnType<typeof MapView>>();
	// When true, the map stays locked/centered on my vehicle as it moves.
	let followMyVehicle = $state(false);
	// Heading-up: rotate the map into the driving direction while following.
	let headingUp = $state(false);
	// In-flight sub-status picker ('technical_halt' | 'breakdown' | null).
	let pendingStatus = $state<'technical_halt' | 'breakdown' | null>(null);
	let pendingNote = $state('');
	// Guards a one-shot auto-arrival so we don't spam the status endpoint.
	let autoArrived = false;
	// Screen Wake Lock so the display stays on while tracking is open.
	let wakeLock: WakeLockSentinel | null = null;

	// Persist the active assignment per convoy so a page reload resumes it.
	const SESSION_KEY = `cp-tracking-session-${convoyId}`;
	// Capture the saved session synchronously at init, before the persistence
	// effect (which clears it while not transmitting) can run.
	const savedSessionRaw = typeof localStorage !== 'undefined' ? localStorage.getItem(SESSION_KEY) : null;

	const isSecure = typeof window !== 'undefined' && window.isSecureContext;

	// vehicle id → label for live markers on the map
	let vehicleNames = $derived(
		new Map((convoy?.convoy_vehicles ?? []).map((cv) => [cv.vehicle.id, cv.vehicle.callsign || cv.vehicle.name]))
	);

	// Effective status (live WebSocket value falls back to the stored convoy value).
	function statusOf(cv: { vehicle: { id: string }; vehicle_status: string; status_level?: string | null }): string {
		return $vehicleStatuses.get(cv.vehicle.id)?.status ?? cv.vehicle_status;
	}
	function levelOf(cv: { vehicle: { id: string }; status_level?: string | null }): string | null {
		return $vehicleStatuses.get(cv.vehicle.id)?.level ?? cv.status_level ?? null;
	}

	// vehicle id → status color so the map markers reflect the current status.
	let vehicleColors = $derived(
		new Map((convoy?.convoy_vehicles ?? []).map((cv) => [cv.vehicle.id, statusColor(statusOf(cv))]))
	);

	// My vehicle's current status (drives the "Mein Status" panel highlight).
	let myStatus = $derived.by(() => {
		const cv = (convoy?.convoy_vehicles ?? []).find((c) => c.vehicle.id === myVehicleId);
		if (!cv) return 'planned';
		return statusOf(cv);
	});

	let activeAlerts = $derived($trackingAlerts.filter((a) => !a.acknowledged));

	// Vehicles still available to pick: a vehicle that is already being transmitted
	// (live) is considered "taken" and hidden — except the one I picked myself.
	let availableVehicles = $derived(
		(convoy?.convoy_vehicles ?? []).filter(
			(cv) => cv.vehicle.id === myVehicleId || !$livePositions.has(cv.vehicle.id)
		)
	);

	// An admin reset the GPS sharing for my vehicle → stop transmitting locally.
	$effect(() => {
		const revoked = $gpsRevoked;
		if (revoked && revoked === myVehicleId && transmitting) {
			stopTransmitting();
			error = 'Die GPS-Freigabe wurde von einem Admin zurückgesetzt.';
		}
		if (revoked) gpsRevoked.set(null);
	});

	// Release the follow lock if my vehicle is deselected or stops sending positions.
	$effect(() => {
		if (followMyVehicle && (!myVehicleId || !$livePositions.has(myVehicleId))) {
			followMyVehicle = false;
		}
	});

	onMount(async () => {
		requestWakeLock();
		document.addEventListener('visibilitychange', handleVisibility);
		try {
			[convoy] = await Promise.all([
				convoysApi.get(convoyId),
				convoysApi.getRoute(convoyId).then(r => { route = r ?? null; }),
				trackingApi.getPositions(convoyId).then(positions => {
					livePositions.set(new Map(positions.map(p => [p.vehicle_id, p])));
				}),
			]);
			// Seed live status map from the loaded convoy so the picker reflects DB state.
			vehicleStatuses.set(new Map((convoy?.convoy_vehicles ?? []).map((cv): [string, VehicleStatusInfo] => [
				cv.vehicle.id, { status: cv.vehicle_status, level: cv.status_level, note: cv.status_note },
			])));
			connectTracking(convoyId);
			restoreSession();
		} catch {
			error = 'Marschverband konnte nicht geladen werden';
		}
	});

	onDestroy(() => {
		disconnectTracking();
		// Reload-safe stop: end the GPS watch but keep the saved session so a
		// page reload can resume; an explicit "stop" button press clears it.
		if (geoWatcher !== null) { navigator.geolocation.clearWatch(geoWatcher); geoWatcher = null; }
		releaseWakeLock();
		document.removeEventListener('visibilitychange', handleVisibility);
	});

	// Restore a previously active assignment after a reload. If the saved vehicle
	// is still part of the convoy, re-select it and resume transmitting.
	function restoreSession() {
		try {
			if (!savedSessionRaw) return;
			const saved = JSON.parse(savedSessionRaw) as { vehicleId: string };
			const known = (convoy?.convoy_vehicles ?? []).some((cv) => cv.vehicle.id === saved.vehicleId);
			if (!known) { localStorage.removeItem(SESSION_KEY); return; }
			myVehicleId = saved.vehicleId;
			startTransmitting();
		} catch {
			localStorage.removeItem(SESSION_KEY);
		}
	}

	// Persist the active assignment while transmitting; clear it once stopped.
	$effect(() => {
		if (typeof localStorage === 'undefined') return;
		if (transmitting && myVehicleId) {
			localStorage.setItem(SESSION_KEY, JSON.stringify({ vehicleId: myVehicleId }));
		} else {
			localStorage.removeItem(SESSION_KEY);
		}
	});

	// Keep the screen awake while the tracking view is open. The lock is dropped
	// automatically when the tab is hidden, so we re-acquire it on return.
	async function requestWakeLock() {
		try {
			if ('wakeLock' in navigator) {
				wakeLock = await navigator.wakeLock.request('screen');
				wakeLock.addEventListener('release', () => { wakeLock = null; });
			}
		} catch { /* denied or unsupported – non-critical */ }
	}

	function releaseWakeLock() {
		wakeLock?.release().catch(() => {});
		wakeLock = null;
	}

	function handleVisibility() {
		if (document.visibilityState === 'visible' && wakeLock === null) requestWakeLock();
	}

	function startTransmitting() {
		if (!myVehicleId) { error = 'Bitte zuerst ein Fahrzeug auswählen'; return; }
		error = '';
		autoArrived = false;
		// Selecting & sending a vehicle auto-advances it to "Unterwegs" (from Geplant).
		if (myStatus === 'planned') setStatus(myVehicleId, 'en_route');
		if (!isSecure) {
			manualMode = true;
			transmitting = true;
			return;
		}
		transmitting = true;
		manualMode = false;
		// Clear a possibly lingering watch so we never accumulate watchers.
		if (geoWatcher !== null) { navigator.geolocation.clearWatch(geoWatcher); geoWatcher = null; }
		geoWatcher = navigator.geolocation.watchPosition(
			(pos) => {
				// Guard against a queued callback firing after the user pressed stop.
				if (!transmitting) return;
				error = '';
				const { latitude: lat, longitude: lon, speed, heading } = pos.coords;
				sendPosition(convoyId, myVehicleId, lat, lon, speed ? speed * 3.6 : undefined, heading ?? undefined);
				maybeAutoArrive(lat, lon);
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
		const wasTransmitting = transmitting;
		transmitting = false;
		manualMode = false;
		// End the GPS sharing: remove our own position so we no longer show as LIVE
		// and the marker disappears (suppress=false → we may re-start immediately).
		if (wasTransmitting && myVehicleId) {
			trackingApi.clearVehiclePosition(convoyId, myVehicleId, false).catch(() => {});
		}
	}

	function handleMapTap(lat: number, lon: number) {
		if (!transmitting || !manualMode || !myVehicleId) return;
		sendPosition(convoyId, myVehicleId, lat, lon, undefined, undefined);
		maybeAutoArrive(lat, lon);
	}

	// Auto-switch my vehicle to "Angekommen" once it enters the destination radius.
	function maybeAutoArrive(lat: number, lon: number) {
		if (autoArrived || !myVehicleId || !convoy?.end_point) return;
		// Only auto-advance from an underway status — never override a halt/breakdown.
		if (myStatus !== 'en_route' && myStatus !== 'planned') return;
		const d = haversine({ lat, lon }, { lat: convoy.end_point.lat, lon: convoy.end_point.lon });
		if (d <= ARRIVAL_RADIUS_M) {
			autoArrived = true;
			setStatus(myVehicleId, 'arrived');
		}
	}

	async function setStatus(vehicleId: string, status: string, level: string | null = null, note: string | null = null) {
		// Optimistic local update so the picker reacts instantly.
		vehicleStatuses.update((m) => { m.set(vehicleId, { status, level, note }); return new Map(m); });
		pendingStatus = null;
		pendingNote = '';
		try {
			await trackingApi.updateVehicleStatus(convoyId, vehicleId, status, level, note);
		} catch { error = 'Status konnte nicht aktualisiert werden'; }
	}

	// A plain-status button (Geplant / Unterwegs / Angekommen) for my vehicle.
	function chooseStatus(status: string) {
		if (!myVehicleId) { error = 'Bitte zuerst ein Fahrzeug auswählen'; return; }
		if (status === 'technical_halt' || status === 'breakdown') {
			pendingStatus = pendingStatus === status ? null : status;
			pendingNote = '';
			return;
		}
		setStatus(myVehicleId, status);
	}

	function confirmPending(level: string) {
		if (!myVehicleId || !pendingStatus) return;
		setStatus(myVehicleId, pendingStatus, level, pendingNote.trim() || null);
	}

	function formatTime(iso: string | null) {
		if (!iso) return '-';
		return new Date(iso).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
	}

	function shiftTime(iso: string, deltaS: number): string {
		return formatTime(new Date(new Date(iso).getTime() + deltaS * 1000).toISOString());
	}

	// --- Live schedule / delay estimation ---------------------------------
	// Reference the convoy "front": the live vehicle furthest along the route.
	let delaySeconds = $derived.by(() => {
		if (!route?.geojson || !route.distance_m || !route.duration_s || !convoy?.start_time) return null;
		const coords = routeCoords(route.geojson);
		if (coords.length < 2) return null;
		let best: number | null = null;
		let maxCovered = -1;
		for (const pos of $livePositions.values()) {
			const est = estimateDelay({
				coords,
				totalDistanceM: route.distance_m,
				totalDurationS: route.duration_s,
				startTime: new Date(convoy.start_time),
				leadPos: { lat: pos.lat, lon: pos.lon },
			});
			if (est && est.coveredM > maxCovered) {
				maxCovered = est.coveredM;
				best = est.delaySeconds;
			}
		}
		return best;
	});

	let hasSchedule = $derived(!!convoy?.waypoints.some(w => w.planned_arrival));

	// --- In-app alert notification (sound + vibration) --------------------
	let lastAlertCount = 0;
	$effect(() => {
		const n = $trackingAlerts.length;
		if (n > lastAlertCount) notify($trackingAlerts[0]?.alert_type === 'breakdown');
		lastAlertCount = n;
	});

	function notify(urgent: boolean) {
		try { navigator.vibrate?.(urgent ? [200, 100, 200, 100, 200] : [200, 100, 200]); } catch { /* unsupported */ }
		try { beep(urgent); } catch { /* audio blocked */ }
	}

	let audioCtx: AudioContext | null = null;
	function beep(urgent: boolean) {
		const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
		if (!Ctx) return;
		audioCtx ??= new Ctx();
		const ctx = audioCtx;
		const tones = urgent ? [880, 660, 880] : [660, 880];
		tones.forEach((freq, i) => {
			const osc = ctx.createOscillator();
			const gain = ctx.createGain();
			osc.type = 'sine';
			osc.frequency.value = freq;
			gain.gain.value = 0.001;
			osc.connect(gain).connect(ctx.destination);
			const t = ctx.currentTime + i * 0.22;
			gain.gain.setValueAtTime(0.0001, t);
			gain.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
			gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.2);
			osc.start(t);
			osc.stop(t + 0.22);
		});
	}

	// Fall back to the vehicles tab whenever the schedule tab is hidden (no
	// waypoints with a planned arrival). `$derived:` is not a rune in runes mode
	// — a real $effect is needed for this to react to convoy changes.
	$effect(() => {
		if (activeTab === 'zeitplan' && !hasSchedule) {
			activeTab = 'fahrzeuge';
		}
	});
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

	<!-- Collapsed-sidebar opener (desktop/tablet) -->
	{#if sidebarCollapsed}
		<button class="rail-open" onclick={() => (sidebarCollapsed = false)} aria-label="Menü einblenden" title="Menü einblenden">›</button>
	{/if}

	<!-- Sidebar -->
	<aside class="sidebar" class:open={sidebarOpen} class:collapsed={sidebarCollapsed}>
		<div class="sidebar-header">
			<div class="logo-wrap">
				<AppLogo width={null} />
				<div class="convoy-name">{convoy?.name ?? 'Laden…'}</div>
				{#if convoy?.organization}<div class="org-name">{convoy.organization}</div>{/if}
			</div>
			<div class="header-right">
				<div class="ws-indicator" class:connected={$trackingActive} title={$trackingActive ? 'Verbunden' : 'Nicht verbunden'}>
					<span class="ws-dot" class:connected={$trackingActive}></span>
					<span class="ws-label">{$trackingActive ? 'Live' : 'Getrennt'}</span>
				</div>
				<button class="collapse-btn" onclick={() => (sidebarCollapsed = true)} aria-label="Menü einklappen" title="Menü einklappen">‹</button>
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
				{#each availableVehicles as cv}
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
			<button class="tab" class:active={activeTab === 'status'} onclick={() => (activeTab = 'status')}>
				Status
				{#if activeAlerts.length > 0}<span class="tab-badge">{activeAlerts.length}</span>{/if}
			</button>
			{#if hasSchedule}
				<button class="tab" class:active={activeTab === 'zeitplan'} onclick={() => (activeTab = 'zeitplan')}>Zeitplan</button>
			{/if}
		</div>

		<div class="tab-content">
			{#if activeTab === 'fahrzeuge'}
				<!-- Read-only vehicle list: marking stays, only the status colors change. -->
				<div class="section">
					{#each (convoy?.convoy_vehicles ?? []) as cv}
						{@const st = statusOf(cv)}
						{@const lvl = levelOf(cv)}
						<div class="vehicle-row">
							<div class="veh-left">
								<span class="status-dot" style="background:{statusColor(st)}"></span>
								<span class="vname">{cv.vehicle.name}</span>
								{#if cv.vehicle.callsign}<span class="tag">{cv.vehicle.callsign}</span>{/if}
								{#if $livePositions.has(cv.vehicle.id)}<span class="live-badge">LIVE</span>{/if}
							</div>
							<span class="status-chip" style="color:{statusColor(st)};border-color:{statusColor(st)}">
								{statusLabel(st)}{#if levelLabel(st, lvl)} · {levelLabel(st, lvl)}{/if}
							</span>
						</div>
					{/each}
					{#if (convoy?.convoy_vehicles ?? []).length === 0}
						<p class="hint">Keine Fahrzeuge im Verband</p>
					{/if}
				</div>

			{:else if activeTab === 'status'}
				<!-- Mein Status: Kurz-Stati zur Kommunikation mit der Konvoiführung -->
				<div class="section">
					<div class="section-title">Mein Status</div>
					{#if !myVehicleId}
						<p class="hint">Wähle oben unter „Meine Position“ ein Fahrzeug, um deinen Status zu melden.</p>
					{:else}
						<div class="status-grid">
							{#each ['planned', 'en_route', 'arrived'] as st}
								<button
									class="status-btn"
									class:active={myStatus === st}
									style="--c:{statusColor(st)}"
									onclick={() => chooseStatus(st)}
								>
									<span class="sb-icon">{STATUS_ICONS[st]}</span>{STATUS_LABELS[st]}
								</button>
							{/each}
							<button
								class="status-btn wide"
								class:active={myStatus === 'technical_halt'}
								class:expanded={pendingStatus === 'technical_halt'}
								style="--c:{statusColor('technical_halt')}"
								onclick={() => chooseStatus('technical_halt')}
							>
								<span class="sb-icon">{STATUS_ICONS.technical_halt}</span>Technischen Halt anfordern
							</button>
							{#if pendingStatus === 'technical_halt'}
								<div class="sub-panel">
									<div class="sub-label">Dringlichkeit wählen</div>
									{#each Object.entries(HALT_LEVEL_LABELS) as [val, label]}
										<button class="sub-btn lvl-{val}" onclick={() => confirmPending(val)}>{label}</button>
									{/each}
									<input class="note-input" placeholder="Grund (optional, z. B. Bio-Pause)" bind:value={pendingNote} maxlength="200" />
								</div>
							{/if}
							<button
								class="status-btn wide"
								class:active={myStatus === 'breakdown'}
								class:expanded={pendingStatus === 'breakdown'}
								style="--c:{statusColor('breakdown')}"
								onclick={() => chooseStatus('breakdown')}
							>
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

				<!-- Meldungen: eingehende TH-/Ausfall-Anforderungen für die Konvoiführung -->
				<div class="section">
					<div class="section-title">
						Meldungen
						{#if activeAlerts.length > 0}
							<button class="link-btn" onclick={acknowledgeAllAlerts}>Alle quittieren</button>
						{/if}
					</div>
					{#if $trackingAlerts.length === 0}
						<p class="hint">Keine aktiven Meldungen.</p>
					{:else}
						{#each $trackingAlerts as a (a.id)}
							<div class="alert-row" class:ack={a.acknowledged} class:breakdown={a.alert_type === 'breakdown'}>
								<div class="alert-main">
									<span class="alert-icon">{STATUS_ICONS[a.alert_type]}</span>
									<div class="alert-text">
										<strong>{a.vehicle_label ?? 'Fahrzeug'}</strong>
										<span class="alert-kind">
											{a.alert_type === 'breakdown' ? 'Ausfall/Störung' : 'Techn. Halt'}{#if levelLabel(a.alert_type, a.level)} · {levelLabel(a.alert_type, a.level)}{/if}
										</span>
										{#if a.note}<span class="alert-note">„{a.note}“</span>{/if}
										<span class="alert-time">{formatTime(a.ts)}</span>
									</div>
								</div>
								<div class="alert-actions">
									{#if !a.acknowledged}
										<button class="link-btn" onclick={() => acknowledgeAlert(a.id)}>Quittieren</button>
									{/if}
									<button class="link-btn dim" onclick={() => dismissAlert(a.id)} aria-label="Entfernen">✕</button>
								</div>
							</div>
						{/each}
					{/if}
				</div>

			{:else if activeTab === 'zeitplan'}
				<div class="section">
					{#if delaySeconds !== null}
						{@const dm = Math.round(delaySeconds / 60)}
						<div class="delay-banner" class:late={dm > 2} class:early={dm < -2} class:ontime={Math.abs(dm) <= 2}>
							{#if dm > 2}⚠ Konvoi ca. {dm} Min hinter Plan
							{:else if dm < -2}⏩ Konvoi ca. {Math.abs(dm)} Min vor Plan
							{:else}✓ Konvoi im Plan{/if}
						</div>
					{:else}
						<p class="hint">Live-Prognose sobald Fahrzeuge Positionen senden.</p>
					{/if}
					<table class="schedule-table">
						<thead><tr><th>Wegpunkt</th><th>Plan</th><th>Prognose</th></tr></thead>
						<tbody>
							{#each (convoy?.waypoints ?? []) as wp}
								<tr>
									<td>{wp.name}</td>
									<td>{formatTime(wp.planned_arrival)}</td>
									<td>
										{#if wp.planned_arrival && delaySeconds !== null}
											{@const dm = Math.round(delaySeconds / 60)}
											<span class="eta" class:late={dm > 2} class:early={dm < -2} class:ontime={Math.abs(dm) <= 2}>
												{shiftTime(wp.planned_arrival, delaySeconds)}
												{#if dm > 2}(+{dm}){:else if dm < -2}({dm}){/if}
											</span>
										{:else}–{/if}
									</td>
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

		<!-- In-app alert banner (TH / Ausfall) -->
		{#if activeAlerts.length > 0}
			{@const a = activeAlerts[0]}
			<div class="alert-banner" class:breakdown={a.alert_type === 'breakdown'}>
				<span class="ab-icon">{STATUS_ICONS[a.alert_type]}</span>
				<div class="ab-text">
					<strong>{a.vehicle_label ?? 'Fahrzeug'}</strong>
					· {a.alert_type === 'breakdown' ? 'Ausfall/Störung' : 'Technischer Halt angefordert'}{#if levelLabel(a.alert_type, a.level)} ({levelLabel(a.alert_type, a.level)}){/if}
					{#if a.note}<div class="ab-note">„{a.note}“</div>{/if}
				</div>
				<button class="ab-btn" onclick={() => { activeTab = 'status'; sidebarOpen = true; }}>Anzeigen</button>
				<button class="ab-btn dim" onclick={() => acknowledgeAlert(a.id)} aria-label="Quittieren">✕</button>
			</div>
		{/if}

		<div class="map-controls">
			{#if routeGeojson}
				<button class="map-ctrl-btn" onclick={() => mapView?.showRoute()} title="Gesamte Route anzeigen">
					🗺️ Route
				</button>
			{/if}
			<button class="map-ctrl-btn" onclick={() => { headingUp = false; mapView?.resetNorth(); }} title="Nach Norden ausrichten">
				🧭 Norden
			</button>
			{#if myVehicleId && $livePositions.has(myVehicleId)}
				<button
					class="map-ctrl-btn"
					class:active={headingUp}
					onclick={() => { headingUp = !headingUp; if (headingUp) followMyVehicle = true; }}
					title="Karte in Fahrtrichtung ausrichten"
				>
					{headingUp ? '🧭 Fahrtrichtung' : '⬆️ Fahrtrichtung'}
				</button>
				<button
					class="map-ctrl-btn"
					class:active={followMyVehicle}
					onclick={() => (followMyVehicle = !followMyVehicle)}
					title={followMyVehicle ? 'Folgen beenden' : 'Karte auf mein Fahrzeug locken'}
				>
					{followMyVehicle ? '🔒 Folgt Fahrzeug' : '🎯 Mein Fahrzeug'}
				</button>
			{/if}
		</div>
		<MapView
			bind:this={mapView}
			startPoint={convoy?.start_point}
			endPoint={convoy?.end_point}
			waypoints={convoy?.waypoints ?? []}
			routeGeojson={routeGeojson}
			livePositions={$livePositions}
			vehicleNames={vehicleNames}
			vehicleColors={vehicleColors}
			headingUp={headingUp}
			focusVehicleId={myVehicleId || null}
			followVehicleId={followMyVehicle ? myVehicleId : null}
			onFollowEnd={() => { followMyVehicle = false; headingUp = false; }}
			clickEnabled={manualMode && transmitting}
			onMapClick={handleMapTap}
			onMapMove={(lat, lon) => (mapCenter = [lat, lon])}
		/>
	</main>
</div>

<style>
	:global(body) { margin: 0; font-family: system-ui, sans-serif; }
	.app { display: flex; height: 100vh; height: 100dvh; overflow: hidden; }

	/* Sidebar */
	.sidebar { width: 320px; min-width: 280px; background: var(--sidebar-bg); color: var(--text-1); display: flex; flex-direction: column; overflow: hidden; transition: width .2s ease, min-width .2s ease; }
	/* Collapsed rail (desktop/tablet): hide the sidebar to free the map. */
	.sidebar.collapsed { width: 0; min-width: 0; border-right: none; }
	.rail-open { position: absolute; top: 50%; left: 0; transform: translateY(-50%); z-index: 30; background: var(--color-primary); color: #fff; border: none; width: 26px; height: 52px; border-radius: 0 10px 10px 0; cursor: pointer; font-size: 1.1rem; box-shadow: 2px 0 8px rgba(0,0,0,.35); }
	.sidebar-header { display: flex; justify-content: space-between; align-items: flex-start; padding: 1rem; border-bottom: 1px solid var(--border); background: var(--sidebar-bg); }
	.logo-wrap { flex: 1; min-width: 0; }
	.logo { font-size: 1rem; font-weight: 700; }
	.convoy-name { font-size: var(--text-xs); color: var(--text-2); margin-top: .25rem; }
	.org-name { font-size: var(--text-xs); color: var(--text-muted); margin-top: .1rem; }
	.header-right { display: flex; flex-direction: column; align-items: flex-end; gap: .4rem; flex-shrink: 0; }
	.collapse-btn { background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border); border-radius: 6px; width: 26px; height: 22px; cursor: pointer; line-height: 1; font-size: 1rem; }
	.collapse-btn:hover { color: var(--text-1); }

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
	.tab { flex: 0 0 auto; padding: .5rem .75rem; background: none; border: none; color: var(--text-2); font-size: var(--text-sm); cursor: pointer; white-space: nowrap; border-radius: 4px; display: inline-flex; align-items: center; gap: .35rem; }
	.tab.active { color: var(--text-1); background: var(--surface-2); font-weight: 600; }
	.tab-badge { background: #E23D28; color: #fff; border-radius: 999px; font-size: 10px; font-weight: 700; min-width: 16px; height: 16px; padding: 0 4px; display: inline-flex; align-items: center; justify-content: center; }

	/* Tab content */
	.tab-content { flex: 1; overflow-y: auto; padding: .75rem 1rem; }
	.section { margin-bottom: 1rem; }
	.section-title { font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); margin-bottom: .5rem; display: flex; align-items: center; justify-content: space-between; }
	.link-btn { background: none; border: none; color: var(--color-primary); font-size: var(--text-xs); cursor: pointer; padding: 0 .15rem; }
	.link-btn.dim { color: var(--text-muted); }

	/* Vehicle rows */
	.vehicle-row { display: flex; align-items: center; justify-content: space-between; padding: .35rem 0; border-bottom: 1px solid var(--border); gap: .4rem; }
	.veh-left { display: flex; align-items: center; gap: .3rem; flex: 1; min-width: 0; }
	.status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
	.vname { font-size: var(--text-sm); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.tag { display: inline-block; padding: .05rem .3rem; background: var(--surface-2); border-radius: 3px; font-size: var(--text-xs); flex-shrink: 0; color: var(--text-2); }
	.live-badge { background: #27ae60; color: white; border-radius: 3px; padding: .05rem .3rem; font-size: var(--text-xs); font-weight: 700; flex-shrink: 0; animation: pulse 1.5s infinite; }
	.status-chip { font-size: var(--text-xs); font-weight: 600; padding: .15rem .4rem; border: 1.5px solid; border-radius: 999px; white-space: nowrap; flex-shrink: 0; }

	/* Status tab — Mein Status */
	.status-grid { display: flex; flex-wrap: wrap; gap: .5rem; }
	.status-btn { flex: 1 1 calc(33% - .5rem); display: flex; flex-direction: column; align-items: center; gap: .25rem; padding: .6rem .4rem; background: var(--surface-2); color: var(--text-1); border: 2px solid var(--border); border-radius: 8px; cursor: pointer; font-size: var(--text-sm); font-weight: 600; text-align: center; }
	.status-btn.wide { flex-basis: 100%; flex-direction: row; justify-content: center; }
	.status-btn .sb-icon { color: var(--c); font-size: 1.1rem; }
	.status-btn:hover { border-color: var(--c); }
	.status-btn.active { border-color: var(--c); background: color-mix(in srgb, var(--c) 18%, var(--surface-2)); box-shadow: inset 0 0 0 1px var(--c); }
	.status-btn.expanded { border-color: var(--c); }
	.sub-panel { flex-basis: 100%; display: flex; flex-direction: column; gap: .4rem; padding: .6rem; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; }
	.sub-label { font-size: var(--text-xs); color: var(--text-muted); }
	.sub-btn { padding: .5rem; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: var(--text-sm); color: #1a1a1a; }
	.sub-btn.lvl-standard { background: #f7dc6f; }
	.sub-btn.lvl-dringend { background: #f1c40f; }
	.sub-btn.lvl-sehr_dringend { background: #e67e22; color: #fff; }
	.sub-btn.break-limited { background: #e67e22; color: #fff; }
	.sub-btn.break-total { background: #E23D28; color: #fff; }
	.note-input { padding: .45rem .5rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-1, var(--sidebar-bg)); color: var(--text-1); font-size: var(--text-sm); }

	/* Status tab — Meldungen */
	.alert-row { display: flex; align-items: flex-start; justify-content: space-between; gap: .5rem; padding: .5rem; border-radius: 8px; border-left: 4px solid #f1c40f; background: var(--surface-2); margin-bottom: .4rem; }
	.alert-row.breakdown { border-left-color: #E23D28; }
	.alert-row.ack { opacity: .55; }
	.alert-main { display: flex; gap: .5rem; min-width: 0; }
	.alert-icon { font-size: 1.1rem; }
	.alert-text { display: flex; flex-direction: column; gap: .1rem; min-width: 0; font-size: var(--text-sm); }
	.alert-kind { color: var(--text-2); font-size: var(--text-xs); }
	.alert-note { font-style: italic; color: var(--text-2); font-size: var(--text-xs); }
	.alert-time { color: var(--text-muted); font-size: var(--text-xs); }
	.alert-actions { display: flex; flex-direction: column; align-items: flex-end; gap: .2rem; flex-shrink: 0; }

	/* Schedule table */
	.schedule-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
	.schedule-table th, .schedule-table td { padding: .5rem; text-align: left; border-bottom: 1px solid var(--border); }
	.schedule-table th { color: var(--text-muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .04em; }
	.delay-banner { padding: .5rem .75rem; border-radius: 8px; font-size: var(--text-sm); font-weight: 600; margin-bottom: .6rem; }
	.delay-banner.late { background: rgba(226,61,40,.18); color: #E23D28; }
	.delay-banner.early { background: rgba(52,152,219,.18); color: #3498db; }
	.delay-banner.ontime { background: rgba(39,174,96,.18); color: #27ae60; }
	.eta.late { color: #E23D28; }
	.eta.early { color: #3498db; }
	.eta.ontime { color: #27ae60; }

	/* Map */
	.map-area { flex: 1; position: relative; }
	.map-area.cursor-crosshair :global(.maplibregl-canvas) { cursor: crosshair; }
	.map-hint-bar { position: absolute; top: 1rem; left: 50%; transform: translateX(-50%); z-index: 10; background: rgba(15,27,36,.9); color: white; padding: .5rem 1.2rem; border-radius: 20px; font-size: var(--text-sm); pointer-events: none; white-space: nowrap; }

	/* Map control buttons (Route / Mein Fahrzeug) */
	.map-controls { position: absolute; right: .75rem; bottom: calc(.75rem + env(safe-area-inset-bottom, 0px)); z-index: 10; display: flex; flex-direction: column; align-items: flex-end; gap: .5rem; max-width: calc(100% - 1.5rem); }
	.map-ctrl-btn { display: flex; align-items: center; gap: .4rem; background: var(--color-primary); color: white; border: none; padding: .55rem .9rem; border-radius: 22px; font-size: var(--text-sm); font-weight: 600; cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,.35); white-space: nowrap; }
	.map-ctrl-btn:hover { background: var(--color-primary-hover); }
	.map-ctrl-btn.active { background: #27ae60; }
	.map-ctrl-btn.active:hover { background: #229954; }

	/* In-app alert banner (map overlay) */
	.alert-banner { position: absolute; top: .75rem; left: 50%; transform: translateX(-50%); z-index: 20; display: flex; align-items: center; gap: .6rem; max-width: min(640px, calc(100% - 1.5rem)); padding: .6rem .8rem; border-radius: 12px; background: #f1c40f; color: #1a1a1a; box-shadow: 0 4px 16px rgba(0,0,0,.4); animation: alert-in .25s ease; }
	.alert-banner.breakdown { background: #E23D28; color: #fff; animation: alert-in .25s ease, flash 1s ease-in-out infinite alternate; }
	.ab-icon { font-size: 1.3rem; flex-shrink: 0; }
	.ab-text { font-size: var(--text-sm); min-width: 0; line-height: 1.3; }
	.ab-note { font-style: italic; font-size: var(--text-xs); }
	.ab-btn { background: rgba(0,0,0,.15); color: inherit; border: none; border-radius: 6px; padding: .35rem .6rem; font-weight: 600; cursor: pointer; font-size: var(--text-sm); flex-shrink: 0; }
	.alert-banner.breakdown .ab-btn { background: rgba(255,255,255,.25); }
	.ab-btn.dim { background: transparent; }
	@keyframes alert-in { from { opacity: 0; transform: translate(-50%, -8px); } to { opacity: 1; transform: translate(-50%, 0); } }
	@keyframes flash { from { box-shadow: 0 4px 16px rgba(0,0,0,.4); } to { box-shadow: 0 0 0 4px rgba(226,61,40,.5), 0 4px 16px rgba(0,0,0,.4); } }

	/* Mobile topbar */
	.topbar { display: none; }
	.sidebar-backdrop { display: none; }

	@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .4; } }

	/* Phone & landscape: slide-out sidebar + topbar.
	   Triggered by a narrow viewport OR a short landscape one (phones/tablets held
	   sideways) so the map gets the full screen and the menu is collapsible. */
	@media (max-width: 700px), (orientation: landscape) and (max-height: 600px) {
		.topbar { display: flex; align-items: center; gap: .75rem; padding: .75rem 1rem; background: var(--sidebar-bg); color: var(--text-1); border-bottom: 1px solid var(--border); position: fixed; top: 0; left: 0; right: 0; z-index: 50; height: 48px; box-sizing: border-box; }
		.hamburger { background: none; border: none; color: var(--text-1); font-size: 1.3rem; cursor: pointer; padding: 0; }
		.topbar-name { flex: 1; font-size: var(--text-sm); font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
		.topbar .ws-dot { margin-left: auto; }

		.app { flex-direction: column; padding-top: 48px; }
		.sidebar { position: fixed; top: 48px; left: 0; bottom: 0; z-index: 40; transform: translateX(-100%); transition: transform .25s ease; width: min(320px, 85vw); min-width: 0; overflow-y: hidden; }
		.sidebar.open { transform: translateX(0); box-shadow: 4px 0 24px rgba(0,0,0,.5); }
		/* The slide-out drawer ignores the desktop collapse state. */
		.sidebar.collapsed { transform: translateX(-100%); }
		.sidebar.collapsed.open { transform: translateX(0); }
		.rail-open { display: none; }
		.collapse-btn { display: none; }
		.sidebar-backdrop { display: block; position: fixed; inset: 0; top: 48px; background: rgba(0,0,0,.4); z-index: 39; border: none; cursor: pointer; }
		.map-area { flex: 1; }
		.alert-banner { top: calc(48px + .5rem); }
	}
</style>
