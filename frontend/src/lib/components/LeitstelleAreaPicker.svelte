<script lang="ts" module>
    export interface AreaSelection {
        /** Gewählte Gebietsschlüssel (leer bei freiem Polygon). */
        districtCodes: string[];
        /** Hochzuladende Grenze (GeoJSON), oder null wenn keine neue Grenze. */
        boundaryFile: File | null;
    }
</script>

<script lang="ts">
    import * as maplibregl from '$lib/map/maplibre';
    import 'maplibre-gl/dist/maplibre-gl.css';
    import { onMount, onDestroy } from 'svelte';
    import { get } from 'svelte/store';
    import { themeStore } from '$lib/stores/theme';
    import { addRegionMask, applyMapTheme } from '$lib/map/region';
    import {
        loadDistricts, districtSubtitle, DISTRICTS_ATTRIBUTION,
        type DistrictFeature, type DistrictProps,
    } from '$lib/geo/districts';

    interface Props {
        initialGeo?: GeoJSON.Geometry | null;
        /** Gebietsschlüssel, die bereits durch andere Leitstellen belegt sind. */
        takenCodes?: string[];
        /** Schlüssel → Name der belegenden Leitstelle (für Tooltip). */
        takenOwnerByCode?: Record<string, string>;
        onchange?: (sel: AreaSelection | null) => void;
    }

    let { initialGeo = null, takenCodes = [], takenOwnerByCode = {}, onchange }: Props = $props();

    let mapContainer: HTMLDivElement | undefined;
    let map: maplibregl.Map | undefined;
    let mapReady = false;
    let popup: maplibregl.Popup | undefined;

    let polygonCoords = $state<[number, number][]>([]);
    let drawingMode = $state(false);
    let districtMode = $state(false);
    let selectedDistricts = $state<string[]>([]);
    let districtsByCode: Record<string, DistrictFeature> = {};
    let loadError = $state('');

    function emit() {
        if (selectedDistricts.length > 0) {
            const features = selectedDistricts.map((c) => districtsByCode[c]).filter(Boolean);
            const fc = { type: 'FeatureCollection', features };
            const blob = new Blob([JSON.stringify(fc)], { type: 'application/json' });
            onchange?.({ districtCodes: selectedDistricts, boundaryFile: new File([blob], 'districts.geojson', { type: 'application/json' }) });
        } else if (!drawingMode && polygonCoords.length >= 3) {
            const closed: [number, number][] = [...polygonCoords, polygonCoords[0]];
            const geo = { type: 'Feature', geometry: { type: 'Polygon', coordinates: [closed] }, properties: {} };
            const blob = new Blob([JSON.stringify(geo)], { type: 'application/json' });
            onchange?.({ districtCodes: [], boundaryFile: new File([blob], 'polygon.geojson', { type: 'application/json' }) });
        } else {
            onchange?.(null);
        }
    }

    function bboxOf(geo: GeoJSON.Geometry): [[number, number], [number, number]] | null {
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        const walk = (a: unknown): void => {
            if (Array.isArray(a) && typeof a[0] === 'number' && typeof a[1] === 'number') {
                const [x, y] = a as [number, number];
                minX = Math.min(minX, x); minY = Math.min(minY, y);
                maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
            } else if (Array.isArray(a)) {
                for (const c of a) walk(c);
            }
        };
        walk((geo as { coordinates?: unknown }).coordinates ?? []);
        if (!isFinite(minX)) return null;
        return [[minX, minY], [maxX, maxY]];
    }

    function updateDraft(geo?: GeoJSON.Geometry) {
        if (!map) return;
        const src = map.getSource('draft') as maplibregl.GeoJSONSource | undefined;
        if (!src) return;
        if (geo) {
            src.setData({ type: 'Feature', geometry: geo, properties: {} } as GeoJSON.Feature);
            return;
        }
        if (polygonCoords.length < 2) {
            src.setData({ type: 'FeatureCollection', features: [] });
            return;
        }
        if (drawingMode) {
            src.setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: polygonCoords }, properties: {} } as GeoJSON.Feature);
        } else {
            const closed: [number, number][] = [...polygonCoords, polygonCoords[0]];
            src.setData({ type: 'Feature', geometry: { type: 'Polygon', coordinates: [closed] }, properties: {} } as GeoJSON.Feature);
        }
    }

    function districtFilter(codes: string[]): maplibregl.FilterSpecification {
        return ['in', ['get', 'code'], ['literal', codes]] as maplibregl.FilterSpecification;
    }

    function updateDistrictSelected() {
        if (map?.getLayer('districts-selected')) map.setFilter('districts-selected', districtFilter(selectedDistricts));
    }

    function setDistrictPickVisible(visible: boolean) {
        if (!map) return;
        const v = visible ? 'visible' : 'none';
        for (const id of ['districts-fill', 'districts-line', 'districts-taken']) {
            if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', v);
        }
        const canvas = map.getCanvas();
        if (canvas) canvas.style.cursor = visible ? 'pointer' : '';
        if (!visible) popup?.remove();
    }

    function ensureDistrictLayers(fc: GeoJSON.FeatureCollection) {
        if (!map || map.getSource('districts')) return;
        const before = map.getLayer('draft-fill') ? 'draft-fill' : undefined;
        map.addSource('districts', { type: 'geojson', data: fc });
        map.addLayer({ id: 'districts-fill', type: 'fill', source: 'districts', paint: { 'fill-color': '#3b82f6', 'fill-opacity': 0.06 } }, before);
        map.addLayer({ id: 'districts-taken', type: 'fill', source: 'districts', filter: districtFilter(takenCodes), paint: { 'fill-color': '#9ca3af', 'fill-opacity': 0.4 } }, before);
        map.addLayer({ id: 'districts-line', type: 'line', source: 'districts', paint: { 'line-color': '#3b82f6', 'line-width': 1, 'line-opacity': 0.5 } }, before);
        map.addLayer({ id: 'districts-selected', type: 'fill', source: 'districts', filter: districtFilter(selectedDistricts), paint: { 'fill-color': '#e74c3c', 'fill-opacity': 0.35 } }, before);
    }

    async function toggleDistrictMode() {
        if (districtMode) { districtMode = false; setDistrictPickVisible(false); return; }
        try {
            const { fc, byCode } = await loadDistricts();
            districtsByCode = byCode;
            ensureDistrictLayers(fc);
        } catch (e: unknown) {
            loadError = e instanceof Error ? e.message : 'Gebietsdaten konnten nicht geladen werden';
            return;
        }
        drawingMode = false;
        districtMode = true;
        updateDistrictSelected();
        setDistrictPickVisible(true);
    }

    function toggleDrawing() {
        drawingMode = !drawingMode;
        if (drawingMode) { districtMode = false; setDistrictPickVisible(false); }
    }

    function reset() {
        polygonCoords = [];
        drawingMode = false;
        selectedDistricts = [];
        updateDistrictSelected();
        updateDraft();
        emit();
    }

    onMount(() => {
        if (!mapContainer) return;
        map = new maplibregl.Map({
            container: mapContainer,
            style: {
                version: 8,
                sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© OpenStreetMap' } },
                layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
            },
            center: [10.5, 48.5],
            zoom: 6,
        });

        map.on('load', () => {
            // Regionsfokus + Hell/Dunkel-Abstimmung (siehe $lib/map/region)
            addRegionMask(map!, get(themeStore));
            applyMapTheme(map!, get(themeStore));
            map!.addSource('draft', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
            map!.addLayer({ id: 'draft-fill', type: 'fill', source: 'draft', paint: { 'fill-color': '#e74c3c', 'fill-opacity': 0.2 } });
            map!.addLayer({ id: 'draft-line', type: 'line', source: 'draft', paint: { 'line-color': '#e74c3c', 'line-width': 2 } });
            mapReady = true;
            if (initialGeo) {
                updateDraft(initialGeo);
                const bb = bboxOf(initialGeo);
                if (bb) map!.fitBounds(bb, { padding: 40 });
            }
        });

        const clickHandler = (e: maplibregl.MapMouseEvent) => {
            if (districtMode) {
                const feats = map!.queryRenderedFeatures(e.point, { layers: ['districts-fill'] });
                const code = feats[0]?.properties?.code as string | undefined;
                if (!code) return;
                selectedDistricts = selectedDistricts.includes(code)
                    ? selectedDistricts.filter((c) => c !== code)
                    : [...selectedDistricts, code];
                updateDistrictSelected();
                emit();
                return;
            }
            if (!drawingMode) return;
            polygonCoords = [...polygonCoords, [e.lngLat.lng, e.lngLat.lat]];
            updateDraft();
        };
        const dblClickHandler = (e: maplibregl.MapMouseEvent) => {
            if (!drawingMode || polygonCoords.length < 3) return;
            e.preventDefault();
            drawingMode = false;
            updateDraft();
            emit();
        };
        const moveHandler = (e: maplibregl.MapMouseEvent) => {
            if (!districtMode || !map) return;
            const feats = map.queryRenderedFeatures(e.point, { layers: ['districts-fill'] });
            const f = feats[0];
            if (!f) { popup?.remove(); return; }
            const props = f.properties as unknown as DistrictProps;
            const owner = takenOwnerByCode[props.code];
            // Build via DOM/textContent — owner (Leitstellenname) is free text.
            const node = document.createElement('div');
            const strong = document.createElement('strong');
            strong.textContent = props.name ?? '';
            node.appendChild(strong);
            // Land/Bundesland dazu: "Zürich" allein sagt nicht, dass gerade ein
            // Schweizer Kanton und kein deutscher Kreis unter dem Zeiger liegt.
            const sub = document.createElement('div');
            sub.className = 'ls-popup-sub';
            sub.textContent = districtSubtitle(props);
            node.appendChild(sub);
            if (owner) {
                node.appendChild(document.createElement('br'));
                node.appendChild(document.createTextNode(`bereits vergeben an: ${owner}`));
            }
            if (!popup) popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 6, className: 'ls-popup' });
            popup.setLngLat(e.lngLat).setDOMContent(node).addTo(map);
        };

        map.on('click', clickHandler);
        map.on('dblclick', dblClickHandler);
        map.on('mousemove', moveHandler);
    });

    onDestroy(() => { popup?.remove(); map?.remove(); map = undefined; });

    // Belegte Kreise aktualisieren, wenn sich die Props ändern.
    $effect(() => {
        const codes = takenCodes;
        if (mapReady && map?.getLayer('districts-taken')) map.setFilter('districts-taken', districtFilter(codes));
    });

    // Karte folgt dem Hell-/Dunkel-Design der App
    $effect(() => {
        const theme = $themeStore;
        if (map) applyMapTheme(map, theme);
    });
</script>

<div class="poly-controls">
    <button type="button" class="btn-small" class:active={drawingMode} onclick={toggleDrawing}>
        {drawingMode ? '✓ Zeichnen aktiv (Doppelklick = fertig)' : '✏ Polygon zeichnen'}
    </button>
    <button type="button" class="btn-small" class:active={districtMode} onclick={toggleDistrictMode}>
        {districtMode ? '✓ Gebietsauswahl aktiv' : '🗺 Gebiet wählen'}
    </button>
    <button type="button" class="btn-small" onclick={reset}>↺ Zurücksetzen</button>
</div>
<div class="poly-map" bind:this={mapContainer}></div>
{#if loadError}
    <p class="poly-hint err">{loadError}</p>
{:else if districtMode}
    <p class="poly-hint">
        Gebiet anklicken zum Hinzufügen/Entfernen — Landkreis (DE), Bezirk (AT) oder Kanton (CH){selectedDistricts.length ? ` · ${selectedDistricts.length} ausgewählt` : ''}{takenCodes.length ? ' · grau = bereits vergeben' : ''} · Grenzen: {DISTRICTS_ATTRIBUTION}
    </p>
{/if}

<style>
    .poly-controls { display: flex; gap: .4rem; font-weight: 400; flex-wrap: wrap; margin-bottom: .4rem; }
    .poly-map { height: 280px; border-radius: 6px; overflow: hidden; border: 1px solid var(--border); }
    .poly-hint { margin: .35rem 0 0; font-size: .72rem; font-weight: 400; color: var(--text-1); opacity: .65; }
    .poly-hint.err { color: #e74c3c; opacity: 1; }
    .btn-small {
        padding: .35rem .6rem; font-size: .8rem; border-radius: 6px; cursor: pointer;
        border: 1px solid var(--border); background: var(--surface, #1e2a3a); color: var(--text-1, #e5e7eb);
    }
    .btn-small.active { background: var(--color-primary, #e74c3c); color: #fff; border-color: transparent; }
    /* Hover-Tooltip lesbar im Dark-Theme (sonst erbt der Text helle Farbe auf weißem Grund) */
    :global(.ls-popup .maplibregl-popup-content) {
        background: #1e2a3a;
        color: #e5e7eb;
        font-size: .78rem;
        line-height: 1.3;
        padding: .4rem .6rem;
        border-radius: 6px;
        box-shadow: 0 2px 10px rgba(0, 0, 0, .45);
    }
    :global(.ls-popup .ls-popup-sub) {
        opacity: .7;
        font-size: .72rem;
    }
    :global(.ls-popup .maplibregl-popup-tip) {
        border-top-color: #1e2a3a;
        border-bottom-color: #1e2a3a;
    }
</style>
