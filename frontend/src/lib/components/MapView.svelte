<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import maplibregl from 'maplibre-gl';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { mapMode } from '$lib/stores/map';
	import type { Waypoint, LageLayer, VehiclePosition } from '$lib/api';
	import type { Geometry, FeatureCollection } from 'geojson';

	interface Props {
		startPoint?: { lat: number; lon: number } | null;
		endPoint?: { lat: number; lon: number } | null;
		waypoints?: Waypoint[];
		routeGeojson?: Geometry | null;
		livePositions?: Map<string, VehiclePosition>;
		lageLayers?: LageLayer[];
		closuresGeojson?: FeatureCollection | null;
		onMapClick?: (lat: number, lon: number) => void;
		onMapMove?: (lat: number, lon: number) => void;
		/** When true, every map click fires onMapClick regardless of mapMode */
		clickEnabled?: boolean;
	}

	let {
		startPoint = null,
		endPoint = null,
		waypoints = [],
		routeGeojson = null,
		livePositions = new Map(),
		lageLayers = [],
		closuresGeojson = null,
		onMapClick,
		onMapMove,
		clickEnabled = false,
	}: Props = $props();

	let mapContainer: HTMLDivElement;
	let map: maplibregl.Map;
	let ready = $state(false);
	let startMarker: maplibregl.Marker | null = null;
	let endMarker: maplibregl.Marker | null = null;
	let waypointMarkers: maplibregl.Marker[] = [];
	let trackingMarkers = new Map<string, maplibregl.Marker>();

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
			if (onMapClick && (clickEnabled || $mapMode !== 'idle')) {
				onMapClick(e.lngLat.lat, e.lngLat.lng);
			}
		});

		map.on('moveend', () => {
			const c = map.getCenter();
			onMapMove?.(c.lat, c.lng);
		});

		map.on('load', () => {
			// Route layer
			map.addSource('route', { type: 'geojson', data: empty() });
			map.addLayer({
				id: 'route-line',
				type: 'line',
				source: 'route',
				layout: { 'line-join': 'round', 'line-cap': 'round' },
				paint: { 'line-color': '#e74c3c', 'line-width': 4 },
			});

			// Sperrungen layer
			map.addSource('closures', { type: 'geojson', data: empty() });
			map.addLayer({
				id: 'closures-line',
				type: 'line',
				source: 'closures',
				paint: { 'line-color': '#f39c12', 'line-width': 3, 'line-dasharray': [4, 2] },
			});
			map.addLayer({
				id: 'closures-circle',
				type: 'circle',
				source: 'closures',
				filter: ['==', '$type', 'Point'],
				paint: { 'circle-color': '#f39c12', 'circle-radius': 6, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1.5 },
			});

			ready = true;
		});
	});

	onDestroy(() => map?.remove());

	function empty(): FeatureCollection {
		return { type: 'FeatureCollection', features: [] };
	}

	function makeMarker(color: string, size = 20): maplibregl.Marker {
		const el = document.createElement('div');
		el.style.cssText = `width:${size}px;height:${size}px;border-radius:50%;background:${color};border:3px solid white;box-shadow:0 2px 6px rgba(0,0,0,.4);cursor:pointer`;
		return new maplibregl.Marker({ element: el });
	}

	function makeArrowMarker(heading: number): maplibregl.Marker {
		const el = document.createElement('div');
		el.textContent = '➤';
		el.style.cssText = `font-size:22px;transform:rotate(${heading}deg);cursor:pointer;filter:drop-shadow(0 2px 3px rgba(0,0,0,.5))`;
		return new maplibregl.Marker({ element: el });
	}

	// Start marker
	$effect(() => {
		if (!map) return;
		startMarker?.remove();
		startMarker = null;
		if (startPoint) {
			startMarker = makeMarker('#27ae60').setLngLat([startPoint.lon, startPoint.lat]).addTo(map);
		}
	});

	// End marker
	$effect(() => {
		if (!map) return;
		endMarker?.remove();
		endMarker = null;
		if (endPoint) {
			endMarker = makeMarker('#e74c3c').setLngLat([endPoint.lon, endPoint.lat]).addTo(map);
		}
	});

	// Waypoint markers
	$effect(() => {
		if (!map) return;
		waypointMarkers.forEach((m) => m.remove());
		const typeColors: Record<string, string> = {
			waypoint: '#3498db', stop: '#9b59b6',
			checkpoint: '#1abc9c', technical_stop: '#e67e22',
		};
		waypointMarkers = waypoints
			.filter((w) => w.lat && w.lon)
			.map((w) => {
				const color = typeColors[w.type] ?? '#3498db';
				return makeMarker(color, 16)
					.setLngLat([w.lon!, w.lat!])
					.setPopup(
						new maplibregl.Popup({ offset: 12 }).setHTML(
							`<strong>${w.name}</strong><br>${w.type}${w.halt_purpose ? ` – ${w.halt_purpose}` : ''}`
						)
					)
					.addTo(map);
			});
	});

	// Route geojson
	$effect(() => {
		if (!ready) return;
		const src = map.getSource('route') as maplibregl.GeoJSONSource | undefined;
		if (!src) return;
		src.setData(
			routeGeojson
				? { type: 'Feature', geometry: routeGeojson, properties: {} }
				: empty()
		);
	});

	// Live tracking markers
	$effect(() => {
		if (!map) return;
		const seen = new Set<string>();
		livePositions.forEach((pos, vehicleId) => {
			seen.add(vehicleId);
			if (trackingMarkers.has(vehicleId)) {
				trackingMarkers.get(vehicleId)!.setLngLat([pos.lon, pos.lat]);
			} else {
				const m = pos.heading != null
					? makeArrowMarker(pos.heading)
					: makeMarker('#f1c40f', 18);
				m.setLngLat([pos.lon, pos.lat])
					.setPopup(new maplibregl.Popup().setHTML(
						`<strong>${vehicleId.slice(0, 8)}…</strong><br>` +
						`${pos.speed_kmh?.toFixed(0) ?? '–'} km/h`
					))
					.addTo(map);
				trackingMarkers.set(vehicleId, m);
			}
		});
		// Remove stale markers
		trackingMarkers.forEach((m, id) => {
			if (!seen.has(id)) { m.remove(); trackingMarkers.delete(id); }
		});
	});

	// Lage layers (dynamic sources)
	let lageSourceIds: string[] = [];
	$effect(() => {
		if (!ready) return;
		// Remove old lage sources/layers
		lageSourceIds.forEach((id) => {
			if (map.getLayer(id + '-line')) map.removeLayer(id + '-line');
			if (map.getLayer(id + '-fill')) map.removeLayer(id + '-fill');
			if (map.getLayer(id + '-circle')) map.removeLayer(id + '-circle');
			if (map.getSource(id)) map.removeSource(id);
		});
		lageSourceIds = [];

		lageLayers.filter((l) => l.visible).forEach((layer) => {
			const sid = `lage-${layer.id}`;
			lageSourceIds.push(sid);
			map.addSource(sid, { type: 'geojson', data: layer.geojson_data as FeatureCollection });
			map.addLayer({ id: sid + '-line', type: 'line', source: sid, paint: { 'line-color': layer.color, 'line-width': 2 } });
			map.addLayer({ id: sid + '-fill', type: 'fill', source: sid, filter: ['==', '$type', 'Polygon'], paint: { 'fill-color': layer.color, 'fill-opacity': 0.2 } });
			map.addLayer({ id: sid + '-circle', type: 'circle', source: sid, filter: ['==', '$type', 'Point'], paint: { 'circle-color': layer.color, 'circle-radius': 6 } });
		});
	});

	// Closures layer
	$effect(() => {
		if (!ready) return;
		const src = map.getSource('closures') as maplibregl.GeoJSONSource | undefined;
		if (!src) return;
		src.setData((closuresGeojson as FeatureCollection) ?? empty());
	});
</script>

<div bind:this={mapContainer} class="map"></div>

<style>
	.map { width: 100%; height: 100%; }
</style>
