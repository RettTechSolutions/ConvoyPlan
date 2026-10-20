<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import MapView from '$lib/components/MapView.svelte';
	import { shareApi, type Waypoint } from '$lib/api';
	import AppLogo from '$lib/components/AppLogo.svelte';

	let data = $state<{ name: string; organization: string | null; start_time: string | null; waypoints: Waypoint[]; geojson: GeoJSON.Geometry | null } | null>(null);
	let error = $state('');

	onMount(async () => {
		try {
			data = await shareApi.get(page.params.token!);
		} catch {
			error = 'Marschverband nicht gefunden oder Link ungültig.';
		}
	});

	function formatTime(iso: string | null) {
		if (!iso) return '–';
		return new Date(iso).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
	}
</script>

<!-- Drei Bereiche statt einer Seitenleiste neben der Karte: Am Schreibtisch
     stehen Kopf und Zeitplan links, die Karte rechts — wie bisher. Am Telefon
     stehen sie untereinander (Kopf, Karte, Zeitplan); neben einer 300 px
     breiten Leiste blieben der Karte dort sonst 90 px. -->
<div class="share-app">
	<header class="share-kopf">
		<div class="share-header">
			<AppLogo width={160} />
		</div>
		{#if data}
			<div class="convoy-info">
				<h1>{data.name}</h1>
				{#if data.organization}<p>{data.organization}</p>{/if}
				{#if data.start_time}<p>Start: {new Date(data.start_time).toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' })}</p>{/if}
			</div>
		{/if}
		{#if error}
			<p class="error">{error}</p>
		{/if}
	</header>

	<section class="share-liste" aria-label="Wegpunkte und Zeitplan">
		{#if data && !error}
			<h2>Wegpunkte & Zeitplan</h2>
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
		{/if}
	</section>

	<div class="share-map">
		{#if data}
			<MapView waypoints={data.waypoints} routeGeojson={data.geojson} />
		{/if}
	</div>
</div>

<style>
	:global(body) { margin: 0; font-family: system-ui, sans-serif; }
	/* `dvh`: iOS Safari misst `vh` mit eingefahrener Adressleiste. */
	.share-app {
		display: grid;
		grid-template-columns: 300px 1fr;
		grid-template-rows: auto 1fr;
		grid-template-areas: 'kopf karte' 'liste karte';
		height: 100vh;
		height: 100dvh;
	}
	.share-kopf { grid-area: kopf; background: var(--sidebar-bg); color: var(--text-1); padding: 1.5rem 1.5rem 0; }
	.share-liste { grid-area: liste; background: var(--sidebar-bg); color: var(--text-1); padding: 0 1.5rem 1.5rem; overflow-y: auto; }
	.share-map { grid-area: karte; min-width: 0; min-height: 0; position: relative; }
	.share-header { display: flex; align-items: center; gap: .5rem; margin-bottom: .75rem; }
	.convoy-info { border-bottom: 1px solid var(--border); padding-bottom: .75rem; }
	.convoy-info h1 { margin: 0 0 .25rem; font-size: var(--text-base); }
	.convoy-info p { margin: .2rem 0; font-size: var(--text-sm); color: var(--text-2); }
	.share-liste h2 { font-size: var(--text-xs); font-weight: 600; margin: 1rem 0 .5rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: .06em; }
	table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
	th, td { padding: .5rem; border-bottom: 1px solid var(--border); text-align: left; }
	th { color: var(--text-muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .04em; }
	td:not(:first-child), th:not(:first-child) { white-space: nowrap; font-variant-numeric: tabular-nums; }
	.error { color: var(--color-primary); font-size: var(--text-sm); }

	@media (max-width: 700px) {
		.share-app {
			grid-template-columns: 1fr;
			/* Karte mit fester Höhe; der Zeitplan darunter scrollt für sich. */
			grid-template-rows: auto 45dvh 1fr;
			grid-template-areas: 'kopf' 'karte' 'liste';
		}
		.share-kopf {
			display: flex; align-items: center; gap: .75rem;
			padding: .5rem max(1rem, env(safe-area-inset-left)) .5rem max(1rem, env(safe-area-inset-right));
			padding-top: max(.5rem, env(safe-area-inset-top));
			border-bottom: 1px solid var(--border);
		}
		.share-header { margin: 0; flex: 0 0 auto; }
		.share-header :global(img) { width: 96px !important; }
		.convoy-info { border: none; padding: 0; min-width: 0; }
		.convoy-info h1 { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
		.convoy-info p { margin: 0; font-size: var(--text-xs); }
		.share-liste { padding: 0 1rem calc(1rem + env(safe-area-inset-bottom)); }
	}
</style>
