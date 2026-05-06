<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import MapView from '$lib/components/MapView.svelte';
	import { shareApi, type Waypoint } from '$lib/api';

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
			<h1>ConvoyPlan</h1>
			{#if data}
				<h2>{data.name}</h2>
				{#if data.organization}<p>{data.organization}</p>{/if}
				{#if data.start_time}<p>Start: {new Date(data.start_time).toLocaleString('de-DE')}</p>{/if}
			{/if}
		</div>

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
	.share-sidebar { width: 300px; background: #1a2744; color: white; padding: 1.5rem; overflow-y: auto; }
	.share-header h1 { margin: 0 0 .5rem; font-size: 1.2rem; }
	.share-header h2 { margin: 0 0 .25rem; font-size: 1rem; }
	.share-header p { margin: .2rem 0; font-size: .85rem; color: rgba(255,255,255,.75); }
	.wp-section h3 { font-size: .9rem; margin: 1rem 0 .5rem; }
	table { width: 100%; border-collapse: collapse; font-size: .8rem; }
	th, td { padding: .3rem .4rem; border-bottom: 1px solid rgba(255,255,255,.1); text-align: left; }
	th { color: rgba(255,255,255,.6); }
	.error { color: #e74c3c; font-size: .9rem; }
	.share-map { flex: 1; }
</style>
