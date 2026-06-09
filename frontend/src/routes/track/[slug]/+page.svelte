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

	const slug = $derived($page.params.slug!);

	let data = $state<TrackPayload | null>(null);
	let gate = $state<TrackGate | null>(null);
	let error = $state('');
	let loading = $state(true);

	let pwInput = $state('');
	let pwBusy = $state(false);

	let livePositions = $state<Map<string, VehiclePosition>>(new Map());
	let ws: WebSocket | null = null;

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
				connectWs(token);
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
		ws.onmessage = (ev) => {
			try {
				const msg = JSON.parse(ev.data);
				if (msg.type === 'status_update') return;  // not visualised here
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
		ws.onerror = () => { /* silent — UI keeps last snapshot */ };
	}

	function fmtTime(iso: string | null) {
		if (!iso) return '–';
		return new Date(iso).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
	}

	onMount(load);
	onDestroy(() => { ws?.close(); });
</script>

<TrackingPwaHead />

<div class="track-app">
	<aside class="track-sidebar">
		<div class="track-header">
			<AppLogo width={160} />
			<h1>ConvoyPlan</h1>
		</div>

		{#if loading}
			<p class="muted">Lade…</p>
		{:else if gate}
			<div class="gate">
				<h2>{gate.convoy_name || 'Tracking'}</h2>
				<p class="muted">Dieser Tracking-Link ist passwortgeschützt.</p>
				<form onsubmit={(e) => { e.preventDefault(); submitPassword(); }}>
					<input
						type="password"
						placeholder="Passwort"
						bind:value={pwInput}
						autocomplete="current-password"
						required
					/>
					<button type="submit" class="primary" disabled={pwBusy || !pwInput}>
						{pwBusy ? 'Prüfe…' : 'Öffnen'}
					</button>
				</form>
				{#if error}<p class="error">{error}</p>{/if}
			</div>
		{:else if data}
			<div class="convoy-info">
				<h2>{data.name}</h2>
				{#if data.organization}<p>{data.organization}</p>{/if}
				{#if data.start_time}<p>Start: {new Date(data.start_time).toLocaleString('de-DE')}</p>{/if}
			</div>

			{#if data.vehicles.length}
				<section>
					<h3>Fahrzeuge</h3>
					<ul class="vehicles">
						{#each data.vehicles as v}
							<li>
								<span class="callsign">{v.callsign ?? '–'}</span>
								<span>{v.name}</span>
								{#if v.sonderfunktion}<span class="badge">{v.sonderfunktion}</span>{/if}
							</li>
						{/each}
					</ul>
				</section>
			{/if}

			<section>
				<h3>Wegpunkte & Zeitplan</h3>
				<table>
					<thead><tr><th>Name</th><th>Ankunft</th><th>Abfahrt</th></tr></thead>
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
			</section>
		{:else if error}
			<p class="error">{error}</p>
		{/if}
	</aside>

	<div class="track-map">
		{#if data}
			<MapView waypoints={data.waypoints as unknown as Waypoint[]} routeGeojson={data.geojson} livePositions={livePositions} />
		{/if}
	</div>
</div>

<style>
	:global(body) { margin: 0; font-family: system-ui, sans-serif; }
	.track-app { display: flex; height: 100vh; height: 100dvh; }
	.track-sidebar { width: 320px; background: var(--sidebar-bg); color: var(--text-1); padding: 1.25rem; overflow-y: auto; box-sizing: border-box; flex-shrink: 0; }
	.track-header { display: flex; align-items: center; gap: .5rem; margin-bottom: .75rem; }
	.track-header h1 { margin: 0; font-size: var(--text-base); font-weight: 700; }
	.convoy-info { margin-bottom: .75rem; border-bottom: 1px solid var(--border); padding-bottom: .75rem; }
	.convoy-info h2 { margin: 0 0 .25rem; font-size: var(--text-base); }
	.convoy-info p { margin: .2rem 0; font-size: var(--text-sm); color: var(--text-2); }
	section { margin-top: 1rem; }
	section h3 { font-size: var(--text-xs); font-weight: 600; margin: 0 0 .5rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: .06em; }
	table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
	th, td { padding: .4rem .5rem; border-bottom: 1px solid var(--border); text-align: left; }
	th { color: var(--text-muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .04em; }
	.vehicles { list-style: none; padding: 0; margin: 0; font-size: var(--text-sm); }
	.vehicles li { display: flex; align-items: center; gap: .5rem; padding: .35rem 0; border-bottom: 1px solid var(--border); }
	.callsign { font-weight: 600; min-width: 3.5rem; }
	.badge { background: var(--surface-2); padding: 0 .4rem; border-radius: 4px; font-size: var(--text-xs); color: var(--text-2); }

	.gate h2 { margin: 0 0 .5rem; font-size: var(--text-base); }
	.gate form { display: flex; flex-direction: column; gap: .5rem; margin-top: .75rem; }
	.gate input { padding: .55rem .7rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
	.gate .primary { padding: .55rem 1rem; background: var(--color-primary); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; }
	.gate .primary:disabled { opacity: .5; cursor: not-allowed; }

	.muted { color: var(--text-muted); font-size: var(--text-sm); }
	.error { color: var(--color-primary); font-size: var(--text-sm); margin-top: .5rem; }
	.track-map { flex: 1; min-height: 0; min-width: 0; }

	@media (max-width: 768px) {
		.track-app { flex-direction: column; }
		.track-map { flex: 1 1 auto; min-height: 55vh; order: 1; }
		.track-sidebar {
			width: 100%;
			max-height: 45vh;
			padding: .75rem 1rem;
			order: 2;
			border-top: 1px solid var(--border);
		}
		.track-header { margin-bottom: .5rem; }
		.convoy-info { margin-bottom: .5rem; padding-bottom: .5rem; }
		section { margin-top: .75rem; }
	}
</style>
