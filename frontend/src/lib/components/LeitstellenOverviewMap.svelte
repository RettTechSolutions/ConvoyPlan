<script lang="ts">
    import * as maplibregl from '$lib/map/maplibre';
    import 'maplibre-gl/dist/maplibre-gl.css';
    import { onMount, onDestroy } from 'svelte';
    import { get } from 'svelte/store';
    import { themeStore } from '$lib/stores/theme';
    import { addGermanyMask, applyMapTheme } from '$lib/map/germany';

    interface Props {
        geojson?: GeoJSON.FeatureCollection | null;
        height?: string;
    }
    let { geojson = null, height = '320px' }: Props = $props();

    let mapContainer: HTMLDivElement | undefined;
    let map: maplibregl.Map | undefined;
    let mapReady = $state(false);
    let popup: maplibregl.Popup | undefined;

    const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

    function bbox(fc: GeoJSON.FeatureCollection): [[number, number], [number, number]] | null {
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        const walk = (a: unknown): void => {
            if (Array.isArray(a) && typeof a[0] === 'number' && typeof a[1] === 'number') {
                const [x, y] = a as [number, number];
                minX = Math.min(minX, x); minY = Math.min(minY, y);
                maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
            } else if (Array.isArray(a)) { for (const c of a) walk(c); }
        };
        for (const f of fc.features) walk(f.geometry && (f.geometry as { coordinates?: unknown }).coordinates);
        if (!isFinite(minX)) return null;
        return [[minX, minY], [maxX, maxY]];
    }

    function render() {
        if (!map || !mapReady) return;
        const data = geojson ?? EMPTY;
        const src = map.getSource('ls') as maplibregl.GeoJSONSource | undefined;
        src?.setData(data);
        const bb = data.features.length ? bbox(data) : null;
        if (bb) map.fitBounds(bb, { padding: 30, maxZoom: 11, duration: 0 });
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
            center: [10.5, 51.0],
            zoom: 5,
        });
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
        map.on('load', () => {
            // Deutschland-Fokus + Hell/Dunkel-Abstimmung (siehe $lib/map/germany)
            addGermanyMask(map!, get(themeStore));
            applyMapTheme(map!, get(themeStore));
            map!.addSource('ls', { type: 'geojson', data: geojson ?? EMPTY });
            map!.addLayer({ id: 'ls-fill', type: 'fill', source: 'ls', paint: { 'fill-color': ['match', ['get', 'status'], 'global', '#2563eb', '#e74c3c'], 'fill-opacity': 0.18 } });
            map!.addLayer({ id: 'ls-line', type: 'line', source: 'ls', paint: { 'line-color': ['match', ['get', 'status'], 'global', '#2563eb', '#e74c3c'], 'line-width': 1.5 } });
            mapReady = true;
            render();

            map!.on('mousemove', 'ls-fill', (e) => {
                const f = e.features?.[0];
                if (!f) return;
                map!.getCanvas().style.cursor = 'pointer';
                const p = f.properties as Record<string, string> | undefined;
                if (!p) return;
                const org = p.org_name ? ` · ${p.org_name}` : '';
                // Build via DOM/textContent — org/Leitstellen names are free text.
                const node = document.createElement('div');
                const strong = document.createElement('strong');
                strong.textContent = p.name ?? '';
                node.appendChild(strong);
                node.appendChild(document.createElement('br'));
                node.appendChild(document.createTextNode(`Anrufgruppe: ${p.anrufgruppe ?? ''}${org}`));
                if (!popup) popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 6, className: 'ls-popup' });
                popup.setLngLat(e.lngLat).setDOMContent(node).addTo(map!);
            });
            map!.on('mouseleave', 'ls-fill', () => { map!.getCanvas().style.cursor = ''; popup?.remove(); });
        });
    });

    onDestroy(() => { popup?.remove(); map?.remove(); map = undefined; });

    $effect(() => { void geojson; render(); });

    // Karte folgt dem Hell-/Dunkel-Design der App
    $effect(() => {
        const theme = $themeStore;
        if (map && mapReady) applyMapTheme(map, theme);
    });
</script>

<div class="ls-overview" style="height:{height}" bind:this={mapContainer}></div>

<style>
    .ls-overview { width: 100%; border-radius: 8px; overflow: hidden; border: 1px solid var(--border); }
    :global(.ls-popup .maplibregl-popup-content) {
        background: #1e2a3a;
        color: #e5e7eb;
        font-size: .78rem;
        line-height: 1.3;
        padding: .4rem .6rem;
        border-radius: 6px;
        box-shadow: 0 2px 10px rgba(0, 0, 0, .45);
    }
    :global(.ls-popup .maplibregl-popup-tip) {
        border-top-color: #1e2a3a;
        border-bottom-color: #1e2a3a;
    }
</style>
