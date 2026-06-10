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
		/** Vehicle to continuously keep centered ("follow" lock). null = no follow. */
		followVehicleId?: string | null;
		/** Called when the follow lock is released by a manual map pan. */
		onFollowEnd?: () => void;
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
		followVehicleId = null,
		onFollowEnd,
		vehicleNames = new Map(),
	}: Props = $props();

	/** Zoom level the map locks to when following a vehicle. */
	const FOLLOW_ZOOM = 15;

	let mapContainer: HTMLDivElement;
	let map: maplibregl.Map;
	let ready = $state(false);
	let startMarker: maplibregl.Marker | null = null;
	let endMarker: maplibregl.Marker | null = null;
	let waypointMarkers: maplibregl.Marker[] = [];

	/** A live vehicle marker plus the bits we need to update it in place. */
	interface LiveMarker {
		marker: maplibregl.Marker;
		arrow: HTMLDivElement | null;
		hasHeading: boolean;
		label: string | undefined;
	}
	let trackingMarkers = new Map<string, LiveMarker>();

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
			attributionControl: false,
		});

		map.addControl(new maplibregl.NavigationControl());
		// Attribution to the left so the bottom-right stays free for map control buttons.
		map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-left');

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

		// A manual pan releases the follow lock. `dragstart` only fires for real
		// user gestures (originalEvent set); our own easeTo/flyTo do not trigger it,
		// and wheel/pinch zoom keeps the lock active.
		map.on('dragstart', (e) => {
			if (e.originalEvent && followVehicleId) onFollowEnd?.();
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

	// A small "flag" that floats above the marker, connected to it by a short stem.
	// It is absolutely positioned, so it does NOT shift the marker's anchor — the
	// dot stays exactly on its coordinate (MapLibre gives the marker element
	// position:absolute, which is the positioning context for this child).
	function labelEl(text: string): HTMLDivElement {
		const wrap = document.createElement('div');
		wrap.style.cssText =
			'position:absolute;left:50%;bottom:100%;transform:translateX(-50%);' +
			'display:flex;flex-direction:column;align-items:center;pointer-events:none';
		const bubble = document.createElement('span');
		bubble.textContent = text;
		bubble.style.cssText =
			'background:rgba(15,27,36,.85);color:#fff;padding:1px 6px;border-radius:4px;' +
			'font:600 11px/1.4 system-ui,sans-serif;white-space:nowrap;box-shadow:0 1px 3px rgba(0,0,0,.4)';
		const stem = document.createElement('div');
		stem.style.cssText = 'width:2px;height:7px;background:rgba(15,27,36,.85)';
		wrap.appendChild(bubble);
		wrap.appendChild(stem);
		return wrap;
	}

	function makeMarker(color: string, size = 20, label?: string): maplibregl.Marker {
		const el = document.createElement('div');
		el.style.cssText = `width:${size}px;height:${size}px;border-radius:50%;background:${color};border:3px solid white;box-shadow:0 2px 6px rgba(0,0,0,.4);cursor:pointer`;
		if (label) el.appendChild(labelEl(label));
		return new maplibregl.Marker({ element: el });
	}

	/**
	 * Build a live vehicle marker: a rotatable arrow when a heading is known,
	 * otherwise a dot, plus an optional label flag. The inner arrow element is
	 * returned so the rotation can be updated in place on later positions; the
	 * marker is only rebuilt when its kind (arrow vs dot) or label changes.
	 */
	function makeLiveMarker(pos: VehiclePosition, label?: string): LiveMarker {
		const hasHeading = pos.heading != null;
		let arrow: HTMLDivElement | null = null;
		let el: HTMLDivElement;
		if (hasHeading) {
			el = document.createElement('div');
			el.style.cssText = 'cursor:pointer';
			arrow = document.createElement('div');
			arrow.textContent = '➤';
			arrow.style.cssText = `font-size:22px;transform:rotate(${pos.heading}deg);filter:drop-shadow(0 2px 3px rgba(0,0,0,.5))`;
			el.appendChild(arrow);
		} else {
			el = document.createElement('div');
			el.style.cssText = 'width:18px;height:18px;border-radius:50%;background:#f1c40f;border:3px solid white;box-shadow:0 2px 6px rgba(0,0,0,.4);cursor:pointer';
		}
		if (label) el.appendChild(labelEl(label));
		return { marker: new maplibregl.Marker({ element: el }), arrow, hasHeading, label };
	}

	function flyToPosition(pos: VehiclePosition) {
		map.flyTo({ center: [pos.lon, pos.lat], zoom: 15, duration: 800 });
	}

	function fitRoute(duration = 800) {
		if (!map || !routeGeojson) return;
		const coords: number[][] =
			routeGeojson.type === 'LineString' ? routeGeojson.coordinates as number[][]
			: routeGeojson.type === 'MultiLineString' ? (routeGeojson.coordinates as number[][][]).flat()
			: [];
		if (coords.length < 2) return;
		const lons = coords.map(c => c[0]);
		const lats = coords.map(c => c[1]);
		map.fitBounds(
			[[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
			{ padding: 60, duration }
		);
	}

	/** Fit the whole route into view again (used by the "Route" button). */
	export function showRoute() {
		fitRoute();
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
		fitRoute();
	});

	// Live tracking markers
	let following: string | null = null;
	$effect(() => {
		if (!map) return;
		const seen = new Set<string>();
		livePositions.forEach((pos, vehicleId) => {
			seen.add(vehicleId);
			const label = vehicleNames.get(vehicleId);
			const hasHeading = pos.heading != null;
			const existing = trackingMarkers.get(vehicleId);
			// Reuse the marker when its kind and label are unchanged — just move it
			// and update the heading rotation. Rebuild when the kind flips (a dot
			// gains a heading) or the label arrives (the convoy names often load
			// after the first position on a fresh page load / reconnect).
			if (existing && existing.hasHeading === hasHeading && existing.label === label) {
				existing.marker.setLngLat([pos.lon, pos.lat]);
				if (hasHeading && existing.arrow) existing.arrow.style.transform = `rotate(${pos.heading}deg)`;
			} else {
				existing?.marker.remove();
				const lm = makeLiveMarker(pos, label);
				lm.marker
					.setLngLat([pos.lon, pos.lat])
					.setPopup(new maplibregl.Popup().setHTML(
						`<strong>${vehicleId.slice(0, 8)}…</strong><br>` +
						`${pos.speed_kmh?.toFixed(0) ?? '–'} km/h`
					))
					.addTo(map);
				trackingMarkers.set(vehicleId, lm);
			}
		});
		// Remove stale markers
		trackingMarkers.forEach((lm, id) => {
			if (!seen.has(id)) { lm.marker.remove(); trackingMarkers.delete(id); }
		});

		// Follow lock: keep the followed vehicle centered as new positions arrive.
		// Locking on (following changed) zooms in once; afterwards we only re-center,
		// preserving whatever zoom the user has chosen meanwhile.
		if (followVehicleId) {
			const pos = livePositions.get(followVehicleId);
			if (pos) {
				if (following !== followVehicleId) {
					following = followVehicleId;
					map.flyTo({ center: [pos.lon, pos.lat], zoom: FOLLOW_ZOOM, duration: 800 });
				} else {
					map.easeTo({ center: [pos.lon, pos.lat], duration: 600 });
				}
			}
		} else {
			following = null;
		}
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
