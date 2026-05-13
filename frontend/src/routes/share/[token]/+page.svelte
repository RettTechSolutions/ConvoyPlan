<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import MapView from '$lib/components/MapView.svelte';
	import { shareApi, type Waypoint } from '$lib/api';
	import AppLogo from '$lib/components/AppLogo.svelte';

	let data = $state<{ name: string; organization: string | null; start_time: string | null; waypoints: Waypoint[]; geojson: GeoJSON.Geometry | null } | null>(null);
	let error = $state('');

	onMount(async () => {
		try {
			data = await shareApi.get($page.params.token);
		} catch {
			error = 'Marschverband nicht gefunden oder Link ungültig.';
		}
	});

	function formatTime(iso: string | null) {
		if (!iso) return '–';
		return new Date(iso).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
	}
</script>

<div class="share-app">
	<div class="share-sidebar">
		<div class="share-header">
			<AppLogo width={160} />
			<h1>ConvoyPlan</h1>
		</div>
		{#if data}
			<div class="convoy-info">
				<h2>{data.name}</h2>
				{#if data.organization}<p>{data.organization}</p>{/if}
				{#if data.start_time}<p>Start: {new Date(data.start_time).toLocaleString('de-DE')}</p>{/if}
			</div>
		{/if}

		{#if error}
			<p class="error">{error}</p>
		{:else if data}
			<div class="wp-section">
				<h3>Wegpunkte & Zeitplan</h3>
				<table>
					<thead><tr><th>Name</th><th>Ankunft</th><th>Abfahrt</th></tr></thead>
					<tbody>
						{#each data.waypoints as wp}
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

	<div class="share-map">
		{#if data}
			<MapView waypoints={data.waypoints} routeGeojson={data.geojson} />
		{/if}
	</div>
</div>

<style>
	:global(body) { margin: 0; font-family: system-ui, sans-serif; }
	.share-app { display: flex; height: 100vh; }
	.share-sidebar { width: 300px; background: var(--sidebar-bg); color: var(--text-1); padding: 1.5rem; overflow-y: auto; }
	.share-header { display: flex; align-items: center; gap: .5rem; margin-bottom: .75rem; }
	.share-header h1 { margin: 0; font-size: var(--text-base); font-weight: 700; }
	.convoy-info { margin-bottom: .75rem; border-bottom: 1px solid var(--border); padding-bottom: .75rem; }
	.convoy-info h2 { margin: 0 0 .25rem; font-size: var(--text-base); }
	.convoy-info p { margin: .2rem 0; font-size: var(--text-sm); color: var(--text-2); }
	.wp-section h3 { font-size: var(--text-xs); font-weight: 600; margin: 1rem 0 .5rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: .06em; }
	table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
	th, td { padding: .5rem; border-bottom: 1px solid var(--border); text-align: left; }
	th { color: var(--text-muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .04em; }
	.error { color: var(--color-primary); font-size: var(--text-sm); }
	.share-map { flex: 1; }
</style>
