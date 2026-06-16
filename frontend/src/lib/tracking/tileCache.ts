// Proactive offline map preparation.
//
// The Service Worker (see vite.config.ts) caches OSM tiles as they are viewed
// (StaleWhileRevalidate). That alone is not enough for tracking: when signal
// drops in an area the driver hasn't panned to yet, those tiles were never
// fetched — so the map (and the route line) go blank. This helper proactively
// warms the tile cache along the whole route corridor while still online, so
// the route stays visible offline.
//
// Politeness: the tile set is bounded and requests are throttled in small
// batches so we don't hammer the public OSM tile servers.

const TILE_HOST = 'https://tile.openstreetmap.org';
// Overview first (always shows the full route), then the common driving zooms.
// Processed in order; once the cap is hit we stop, so the overview is preferred.
const ZOOMS = [12, 13, 14, 15];
// Tiles around each route point → covers the corridor width, not just the line.
const BUFFER = 1; // 3×3 tiles per point
// Hard cap on prefetched tiles (OSM politeness + Service-Worker cache budget).
const MAX_TILES = 2500;
const BATCH = 6; // concurrent requests per batch
const BATCH_DELAY_MS = 120;

function lon2tile(lon: number, z: number): number {
	return Math.floor(((lon + 180) / 360) * 2 ** z);
}
function lat2tile(lat: number, z: number): number {
	const r = (lat * Math.PI) / 180;
	return Math.floor(((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 2 ** z);
}

// Remember which route we already warmed so re-renders don't re-trigger it.
let warmedKey: string | null = null;

/**
 * Warm the OSM tile cache along a route corridor.
 * @param coords route polyline as [lon, lat] pairs (see routeCoords())
 * @param key    stable identifier for this route (e.g. convoy id) — dedupes runs
 */
export async function prefetchRouteTiles(coords: number[][], key: string): Promise<void> {
	if (typeof navigator !== 'undefined' && navigator.onLine === false) return;
	if (!coords || coords.length === 0) return;
	if (warmedKey === key) return;
	warmedKey = key;

	const tiles = new Set<string>();
	outer: for (const z of ZOOMS) {
		const n = 2 ** z;
		for (const [lon, lat] of coords) {
			if (typeof lon !== 'number' || typeof lat !== 'number') continue;
			const tx = lon2tile(lon, z);
			const ty = lat2tile(lat, z);
			for (let dx = -BUFFER; dx <= BUFFER; dx++) {
				for (let dy = -BUFFER; dy <= BUFFER; dy++) {
					const x = tx + dx;
					const y = ty + dy;
					if (x < 0 || y < 0 || x >= n || y >= n) continue;
					tiles.add(`${z}/${x}/${y}`);
					if (tiles.size >= MAX_TILES) break outer;
				}
			}
		}
	}

	const urls = [...tiles].map((t) => `${TILE_HOST}/${t}.png`);
	for (let i = 0; i < urls.length; i += BATCH) {
		// Stop early if connectivity drops mid-prefetch.
		if (typeof navigator !== 'undefined' && navigator.onLine === false) break;
		await Promise.all(
			urls.slice(i, i + BATCH).map((u) => fetch(u).then(() => {}).catch(() => {}))
		);
		await new Promise((r) => setTimeout(r, BATCH_DELAY_MS));
	}
}

/** Allow a fresh prefetch run (e.g. when the route changes). */
export function resetTilePrefetch(): void {
	warmedKey = null;
}
