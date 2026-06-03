<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import maplibregl from 'maplibre-gl';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { get } from 'svelte/store';
	import { mapMode } from '$lib/stores/map';
	import type { Waypoint, VehiclePosition } from '$lib/api';
	import type { Geometry, FeatureCollection } from 'geojson';

	interface Props {
		startPoint?: { lat: number; lon: number } | null;
		endPoint?: { lat: number; lon: number } | null;
		waypoints?: Waypoint[];
		routeGeojson?: Geometry | null;
		livePositions?: Map<string, VehiclePosition>;
		closuresGeojson?: FeatureCollection | null;
		onMapClick?: (lat: number, lon: number) => void;
		onMapMove?: (lat: number, lon: number) => void;
		/** When true, every map click fires onMapClick regardless of mapMode */
		clickEnabled?: boolean;
		/** Vehicle to zoom to once on selection (e.g. the user's own vehicle) */
		focusVehicleId?: string | null;
		/** Optional vehicle id → display name map for live marker labels */
		vehicleNames?: Map<string, string>;
	}

	let {
		startPoint = null,
		endPoint = null,
		waypoints = [],
		routeGeojson = null,
		livePositions = new Map(),
		closuresGeojson = null,
		onMapClick,
		onMapMove,
		clickEnabled = false,
		focusVehicleId = null,
		vehicleNames = new Map(),
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
			const mode = get(mapMode);
			if (onMapClick && (clickEnabled || mode !== 'idle')) {
				onMapClick(e.lngLat.lat, e.lngLat.lng);
			}
		});

		// Cursor: crosshair in placing mode, default otherwise
		mapMode.subscribe((mode) => {
			if (map) map.getCanvas().style.cursor = mode !== 'idle' ? 'crosshair' : '';
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

	// Small "flag" label that floats above a marker without shifting its anchor.
	function labelEl(text: string): HTMLSpanElement {
		const tag = document.createElement('span');
		tag.textContent = text;
		tag.style.cssText =
			'position:absolute;left:50%;bottom:calc(100% + 5px);transform:translateX(-50%);' +
			'background:rgba(15,27,36,.85);color:#fff;padding:1px 6px;border-radius:4px;' +
			'font:600 11px/1.4 system-ui,sans-serif;white-space:nowrap;pointer-events:none;' +
			'box-shadow:0 1px 3px rgba(0,0,0,.4)';
		return tag;
	}

	function makeMarker(color: string, size = 20, label?: string): maplibregl.Marker {
		const el = document.createElement('div');
		el.style.cssText = `position:relative;width:${size}px;height:${size}px;border-radius:50%;background:${color};border:3px solid white;box-shadow:0 2px 6px rgba(0,0,0,.4);cursor:pointer`;
		if (label) el.appendChild(labelEl(label));
		return new maplibregl.Marker({ element: el });
	}

	function makeArrowMarker(heading: number, label?: string): maplibregl.Marker {
		const el = document.createElement('div');
		el.style.cssText = 'position:relative;cursor:pointer';
		const arrow = document.createElement('div');
		arrow.textContent = '➤';
		arrow.style.cssText = `font-size:22px;transform:rotate(${heading}deg);filter:drop-shadow(0 2px 3px rgba(0,0,0,.5))`;
		el.appendChild(arrow);
		if (label) el.appendChild(labelEl(label));
		return new maplibregl.Marker({ element: el });
	}

	function flyToPosition(pos: VehiclePosition) {
		map.flyTo({ center: [pos.lon, pos.lat], zoom: 15, duration: 800 });
	}

	/** Recenter the map on a vehicle's latest live position (used by the recenter button). */
	export function recenterOnVehicle(vehicleId: string) {
		const pos = livePositions.get(vehicleId);
		if (map && pos) flyToPosition(pos);
	}

	// Start marker
	$effect(() => {
		if (!map) return;
		startMarker?.remove();
		startMarker = null;
		if (startPoint) {
			startMarker = makeMarker('#27ae60', 20, 'Start').setLngLat([startPoint.lon, startPoint.lat]).addTo(map);
		}
	});

	// End marker
	$effect(() => {
		if (!map) return;
		endMarker?.remove();
		endMarker = null;
		if (endPoint) {
			endMarker = makeMarker('#e74c3c', 20, 'Ziel').setLngLat([endPoint.lon, endPoint.lat]).addTo(map);
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
				return makeMarker(color, 16, w.name)
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
		if (routeGeojson) {
			const coords: number[][] =
				routeGeojson.type === 'LineString' ? routeGeojson.coordinates as number[][]
				: routeGeojson.type === 'MultiLineString' ? (routeGeojson.coordinates as number[][][]).flat()
				: [];
			if (coords.length > 1) {
				const lons = coords.map(c => c[0]);
				const lats = coords.map(c => c[1]);
				map.fitBounds(
					[[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
					{ padding: 60, duration: 800 }
				);
			}
		}
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
				const label = vehicleNames.get(vehicleId);
				const m = pos.heading != null
					? makeArrowMarker(pos.heading, label)
					: makeMarker('#f1c40f', 18, label);
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

	// Zoom once to the focused vehicle as soon as a position is available for it.
	// The user can pan freely afterwards; re-focusing only happens via recenterOnVehicle().
	let focusedVehicle: string | null = null;
	$effect(() => {
		if (!map) return;
		if (!focusVehicleId) { focusedVehicle = null; return; }
		const pos = livePositions.get(focusVehicleId);
		if (pos && focusedVehicle !== focusVehicleId) {
			focusedVehicle = focusVehicleId;
			flyToPosition(pos);
		}
	});

	// Lage layers (dynamic sources)
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
