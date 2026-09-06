<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import * as maplibregl from '$lib/map/maplibre';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { get } from 'svelte/store';
	import { mapMode } from '$lib/stores/map';
	import { themeStore } from '$lib/stores/theme';
	import { addRegionMask, applyMapTheme } from '$lib/map/region';
	import type { Waypoint, VehiclePosition } from '$lib/api';
	import type { Geometry, FeatureCollection } from 'geojson';

	interface Props {
		startPoint?: { lat: number; lon: number } | null;
		endPoint?: { lat: number; lon: number } | null;
		waypoints?: Waypoint[];
		routeGeojson?: Geometry | null;
		livePositions?: Map<string, VehiclePosition>;
		closuresGeojson?: FeatureCollection | null;
		/** Live-Verkehrslage (HERE/TomTom): LineStrings mit jamFactor 0–10. */
		flowGeojson?: FeatureCollection | null;
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
		/** Optional vehicle id → marker color (status color). Defaults to red. */
		vehicleColors?: Map<string, string>;
		/** Heading-up: rotate the map so the followed vehicle's heading points up. */
		headingUp?: boolean;
	}

	let {
		startPoint = null,
		endPoint = null,
		waypoints = [],
		routeGeojson = null,
		livePositions = new Map(),
		closuresGeojson = null,
		flowGeojson = null,
		onMapClick,
		onMapMove,
		clickEnabled = false,
		focusVehicleId = null,
		followVehicleId = null,
		onFollowEnd,
		vehicleNames = new Map(),
		vehicleColors = new Map(),
		headingUp = false,
	}: Props = $props();

	const DEFAULT_MARKER_COLOR = '#e74c3c';

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
		svg: SVGPolygonElement | null;
		hasHeading: boolean;
		heading: number;
		label: string | undefined;
		color: string;
	}
	let trackingMarkers = new Map<string, LiveMarker>();

	/**
	 * Rotate an arrow marker so it points along the vehicle's true heading,
	 * compensating for the current map bearing — i.e. the arrow always shows the
	 * real driving direction even when the map itself is rotated. The label flag
	 * stays screen-upright because only the inner arrow element is rotated.
	 */
	function applyArrowRotation(lm: LiveMarker) {
		if (!lm.arrow || !lm.hasHeading) return;
		const bearing = map ? map.getBearing() : 0;
		lm.arrow.style.transform = `rotate(${lm.heading - bearing}deg)`;
	}

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
				layers: [
					{ id: 'osm', type: 'raster', source: 'osm' },
				],
			},
			center: [11.5, 50.7],
			zoom: 5.7,
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

		// Keep arrow markers pointing along the true heading while the map rotates.
		map.on('rotate', () => trackingMarkers.forEach(applyArrowRotation));

		// A manual pan releases the follow lock. `dragstart` only fires for real
		// user gestures (originalEvent set); our own easeTo/flyTo do not trigger it,
		// and wheel/pinch zoom keeps the lock active.
		map.on('dragstart', (e) => {
			if (e.originalEvent && followVehicleId) onFollowEnd?.();
		});

		map.on('load', () => {
			// Regionsfokus: alles außerhalb der aktiv geladenen Kartenregion wird
			// abgedunkelt, weil die Routenberechnung nur dort möglich ist. Der
			// Umriss kommt vom Backend und folgt damit einem Regionswechsel im
			// Admin-Panel (siehe $lib/map/region). Zuerst hinzugefügt, damit
			// Route, Sperrungen und Marker darüber liegen.
			addRegionMask(map, get(themeStore));
			applyMapTheme(map, get(themeStore));

			// Live-Verkehrslage (Flow) — zuunterst, damit Route und Sperrungen
			// darüber sichtbar bleiben. Ampelfarbe nach jamFactor (0 = frei,
			// 10 = Stillstand); nur befüllt, wenn ein Anbieter-Key gesetzt ist.
			map.addSource('flow', { type: 'geojson', data: empty() });
			map.addLayer({
				id: 'flow-line',
				type: 'line',
				source: 'flow',
				layout: { 'line-join': 'round', 'line-cap': 'round' },
				paint: {
					'line-color': [
						'interpolate', ['linear'], ['to-number', ['get', 'jamFactor'], 0],
						0, '#2ecc71', 3, '#f1c40f', 6, '#e67e22', 10, '#c0392b',
					],
					'line-width': 6,
					'line-opacity': 0.7,
				},
			});

			// Route layer
			map.addSource('route', { type: 'geojson', data: empty() });
			map.addLayer({
				id: 'route-line',
				type: 'line',
				source: 'route',
				layout: { 'line-join': 'round', 'line-cap': 'round' },
				paint: { 'line-color': '#e74c3c', 'line-width': 4 },
			});

			// Sperrungen layer — Farbe nach Schweregrad: rot = Voll-/Sperrung,
			// gelb = Verkehrswarnung (Unfall/Hindernis), orange = Baustelle.
			// Speist sich aus mehreren Quellen (Overpass + Autobahn-API); die
			// `service`/`isBlocked`-Properties liefern beide Quellen mit.
			map.addSource('closures', { type: 'geojson', data: empty() });
			map.addLayer({
				id: 'closures-line',
				type: 'line',
				source: 'closures',
				paint: {
					'line-color': [
						'case',
						['any', ['==', ['get', 'isBlocked'], 'true'], ['==', ['get', 'service'], 'closure']], '#e74c3c',
						['==', ['get', 'service'], 'warning'], '#f1c40f',
						'#f39c12',
					],
					'line-width': 3,
					'line-dasharray': [4, 2],
				},
			});
			map.addLayer({
				id: 'closures-circle',
				type: 'circle',
				source: 'closures',
				filter: ['==', '$type', 'Point'],
				paint: {
					'circle-color': [
						'case',
						['any', ['==', ['get', 'isBlocked'], 'true'], ['==', ['get', 'service'], 'closure']], '#e74c3c',
						['==', ['get', 'service'], 'warning'], '#f1c40f',
						'#f39c12',
					],
					'circle-radius': 6,
					'circle-stroke-color': '#fff',
					'circle-stroke-width': 1.5,
				},
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

	/**
	 * Build popup content via the DOM (textContent) instead of setHTML so that
	 * user-controlled values (waypoint names, halt purpose, …) can never inject
	 * markup. Used on public share/track pages → must stay XSS-safe.
	 */
	function popupNode(title: string, subtitle: string): HTMLDivElement {
		const div = document.createElement('div');
		const strong = document.createElement('strong');
		strong.textContent = title;
		div.appendChild(strong);
		div.appendChild(document.createElement('br'));
		div.appendChild(document.createTextNode(subtitle));
		return div;
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
	function makeLiveMarker(pos: VehiclePosition, label?: string, color = DEFAULT_MARKER_COLOR): LiveMarker {
		const hasHeading = pos.heading != null;
		const heading = pos.heading ?? 0;
		let arrow: HTMLDivElement | null = null;
		let svg: SVGPolygonElement | null = null;
		let el: HTMLDivElement;
		if (hasHeading) {
			el = document.createElement('div');
			el.style.cssText = 'cursor:pointer';
			arrow = document.createElement('div');
			arrow.style.cssText = `width:38px;height:38px;filter:drop-shadow(0 2px 4px rgba(0,0,0,.55));`;
			arrow.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 38 38" width="38" height="38"><polygon points="19,4 31,32 19,25 7,32" fill="${color}" stroke="white" stroke-width="2.5" stroke-linejoin="round"/></svg>`;
			svg = arrow.querySelector('polygon');
			el.appendChild(arrow);
		} else {
			el = document.createElement('div');
			el.style.cssText = `width:18px;height:18px;border-radius:50%;background:${color};border:3px solid white;box-shadow:0 2px 6px rgba(0,0,0,.4);cursor:pointer`;
		}
		if (label) el.appendChild(labelEl(label));
		const lm: LiveMarker = { marker: new maplibregl.Marker({ element: el }), arrow, svg, hasHeading, heading, label, color };
		applyArrowRotation(lm);
		return lm;
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

	/** Reset the map orientation to north-up (and level). */
	export function resetNorth() {
		map?.easeTo({ bearing: 0, pitch: 0, duration: 400 });
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
						new maplibregl.Popup({ offset: 12 }).setDOMContent(
							popupNode(w.name, `${w.type}${w.halt_purpose ? ` – ${w.halt_purpose}` : ''}`)
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
			const color = vehicleColors.get(vehicleId) ?? DEFAULT_MARKER_COLOR;
			const hasHeading = pos.heading != null;
			const existing = trackingMarkers.get(vehicleId);
			// Reuse the marker when its kind and label are unchanged — just move it,
			// recolor it and update the heading rotation. Rebuild when the kind flips
			// (a dot gains a heading) or the label arrives (the convoy names often load
			// after the first position on a fresh page load / reconnect).
			if (existing && existing.hasHeading === hasHeading && existing.label === label) {
				existing.marker.setLngLat([pos.lon, pos.lat]);
				if (existing.color !== color) {
					existing.color = color;
					if (existing.svg) existing.svg.setAttribute('fill', color);
					else existing.marker.getElement().style.background = color;
				}
				if (hasHeading) {
					existing.heading = pos.heading ?? existing.heading;
					applyArrowRotation(existing);
				}
			} else {
	      existing?.marker.remove();
	      const lm = makeLiveMarker(pos, label, color);
	      lm.marker
		      .setLngLat([pos.lon, pos.lat])
		      .setPopup(new maplibregl.Popup().setDOMContent(
			      popupNode(label ?? `${vehicleId.slice(0, 8)}…`, `${pos.speed_kmh?.toFixed(0) ?? '–'} km/h`)
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
		// preserving whatever zoom the user has chosen meanwhile. In heading-up mode
		// the map bearing tracks the vehicle heading so the route ahead points up.
		if (followVehicleId) {
			const pos = livePositions.get(followVehicleId);
			if (pos) {
				const bearing = headingUp && pos.heading != null ? pos.heading : undefined;
				if (following !== followVehicleId) {
					following = followVehicleId;
					map.flyTo({ center: [pos.lon, pos.lat], zoom: FOLLOW_ZOOM, bearing, duration: 800 });
				} else {
					map.easeTo({ center: [pos.lon, pos.lat], bearing, duration: 600 });
				}
			}
		} else {
			following = null;
		}
	});

	// Leaving heading-up mode snaps the map back to north so it isn't left tilted.
	let prevHeadingUp = false;
	$effect(() => {
		if (!map) return;
		if (prevHeadingUp && !headingUp) map.easeTo({ bearing: 0, duration: 400 });
		prevHeadingUp = headingUp;
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

	// Live-Verkehrslage layer
	$effect(() => {
		if (!ready) return;
		const src = map.getSource('flow') as maplibregl.GeoJSONSource | undefined;
		if (!src) return;
		src.setData((flowGeojson as FeatureCollection) ?? empty());
	});

	// Karte folgt dem Hell-/Dunkel-Design der App
	$effect(() => {
		const theme = $themeStore;
		if (!ready) return;
		applyMapTheme(map, theme);
	});
</script>

<div bind:this={mapContainer} class="map"></div>

<style>
	.map { width: 100%; height: 100%; }
</style>
