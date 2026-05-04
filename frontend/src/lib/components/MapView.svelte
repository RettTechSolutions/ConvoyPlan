<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import maplibregl from 'maplibre-gl';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { mapMode } from '$lib/stores/map';
	import type { Waypoint } from '$lib/api';
	import type { Geometry } from 'geojson';

	interface Props {
		startPoint?: { lat: number; lon: number } | null;
		endPoint?: { lat: number; lon: number } | null;
		waypoints?: Waypoint[];
		routeGeojson?: Geometry | null;
		onMapClick?: (lat: number, lon: number) => void;
	}

	let {
		startPoint = null,
		endPoint = null,
		waypoints = [],
		routeGeojson = null,
		onMapClick,
	}: Props = $props();

	let mapContainer: HTMLDivElement;
	let map: maplibregl.Map;
	let startMarker: maplibregl.Marker | null = null;
	let endMarker: maplibregl.Marker | null = null;
	let waypointMarkers: maplibregl.Marker[] = [];

	onMount(() => {
		map = new maplibregl.Map({
			container: mapContainer,
			style: {
				version: 8,
				sources: {
					osm: {
						type: 'raster',
						tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
						tileSize: 256,
						attribution: '© OpenStreetMap contributors',
					},
				},
				layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
			},
			center: [10.0, 51.5],
			zoom: 6,
		});

		map.addControl(new maplibregl.NavigationControl());

		map.on('click', (e) => {
			if ($mapMode !== 'idle' && onMapClick) {
				onMapClick(e.lngLat.lat, e.lngLat.lng);
			}
		});

		map.on('load', () => {
			map.addSource('route', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
			map.addLayer({
				id: 'route-line',
				type: 'line',
				source: 'route',
				layout: { 'line-join': 'round', 'line-cap': 'round' },
				paint: { 'line-color': '#e74c3c', 'line-width': 4 },
			});
		});
	});

	onDestroy(() => map?.remove());

	function makeMarker(color: string): maplibregl.Marker {
		const el = document.createElement('div');
		el.style.cssText = `width:20px;height:20px;border-radius:50%;background:${color};border:3px solid white;box-shadow:0 2px 6px rgba(0,0,0,.4);cursor:pointer`;
		return new maplibregl.Marker({ element: el });
	}

	$effect(() => {
		if (!map) return;
		startMarker?.remove();
		if (startPoint) {
			startMarker = makeMarker('#27ae60').setLngLat([startPoint.lon, startPoint.lat]).addTo(map);
		}
	});

	$effect(() => {
		if (!map) return;
		endMarker?.remove();
		if (endPoint) {
			endMarker = makeMarker('#e74c3c').setLngLat([endPoint.lon, endPoint.lat]).addTo(map);
		}
	});

	$effect(() => {
		if (!map) return;
		waypointMarkers.forEach((m) => m.remove());
		waypointMarkers = waypoints
			.filter((w) => w.lat && w.lon)
			.map((w) =>
				makeMarker('#3498db')
					.setLngLat([w.lon!, w.lat!])
					.setPopup(new maplibregl.Popup().setText(w.name))
					.addTo(map)
			);
	});

	$effect(() => {
		if (!map || !map.isStyleLoaded()) return;
		const source = map.getSource('route') as maplibregl.GeoJSONSource | undefined;
		if (!source) return;
		if (routeGeojson) {
			source.setData({ type: 'Feature', geometry: routeGeojson, properties: {} });
		} else {
			source.setData({ type: 'FeatureCollection', features: [] });
		}
	});
</script>

<div bind:this={mapContainer} class="map"></div>

<style>
	.map {
		width: 100%;
		height: 100%;
	}
</style>
