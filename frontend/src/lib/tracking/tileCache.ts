// Proactive offline map preparation.
//
// The Service Worker (see vite.config.ts) caches OSM tiles as they are viewed
// (StaleWhileRevalidate). That alone is not enough for tracking: when signal
// drops in an area the driver hasn't panned to yet, those tiles were never
// fetched — so the map (and the route line) go blank. This helper proactively
// warms the tile cache along the whole route corridor while still online, so
// the route stays visible offline.
//
// Why write the Cache Storage directly instead of relying on the Service
// Worker interception: on the very first visit the SW is installed but does
// not yet *control* the page, so plain `fetch()` calls would NOT be routed
// through the SW and would never be cached — exactly when warming matters most
// (a freshly opened tracking link before any reload). Writing into the same
// named cache ('osm-tiles') guarantees the corridor is cached immediately and
// the SW's StaleWhileRevalidate then serves from that very cache.
//
// Politeness: the tile set is bounded and requests are throttled in small
// batches, and tiles already in the cache are skipped so re-runs are cheap.
//
// Tiles come from the instance's own proxy (/api/tiles), not from the tile
// server directly — the server decides how much may be prefetched
// (GET /api/tiles/config): on the public OSM server only the overview zooms and
// a small cap, since its usage policy discourages bulk prefetching; with an own
// or commercial tile server the full corridor below.

import { tileBase } from '$lib/map/tiles';
import { getBaseUrl } from '$lib/api/client';
// Must match the runtime cache name configured in vite.config.ts so the Service
// Worker serves the tiles we pre-warm here.
const CACHE_NAME = 'osm-tiles';
// Overview first (always shows the full route), then the common driving zooms
// up to the follow zoom (15) and one step closer (16) for junction detail.
// Processed in order; once the cap is hit we stop, so the overview is preferred.
const FULL_ZOOMS = [12, 13, 14, 15, 16];
// Tiles around each route point → covers the corridor width, not just the line.
const BUFFER = 1; // 3×3 tiles per point
// Hard cap on prefetched tiles (OSM politeness + Service-Worker cache budget).
// Generous enough to hold a long route corridor across all the zooms above.
const FULL_MAX_TILES = 8000;
// Fallback when the profile cannot be fetched: the conservative OSM profile.
const FALLBACK = { zooms: [12, 13, 14], max_tiles: 1500 };

interface PrefetchProfile {
	zooms: number[];
	max_tiles: number;
}

async function loadProfile(): Promise<PrefetchProfile> {
	try {
		const res = await fetch(`${getBaseUrl()}/api/tiles/config`, { credentials: 'same-origin' });
		if (!res.ok) return FALLBACK;
		const cfg = await res.json();
		const p = cfg?.prefetch;
		if (Array.isArray(p?.zooms) && typeof p?.max_tiles === 'number') {
			return {
				zooms: p.zooms.filter((z: unknown) => typeof z === 'number' && FULL_ZOOMS.includes(z)),
				max_tiles: Math.min(p.max_tiles, FULL_MAX_TILES),
			};
		}
	} catch {
		/* offline or older server — fall back */
	}
	return FALLBACK;
}
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

	const profile = await loadProfile();
	const tiles = new Set<string>();
	outer: for (const z of profile.zooms) {
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
					if (tiles.size >= profile.max_tiles) break outer;
				}
			}
		}
	}

	const host = tileBase();
	const urls = [...tiles].map((t) => `${host}/${t}.png`);

	// Prefer the Cache Storage API so warming works even before the Service
	// Worker controls the page; fall back to a plain fetch (SW interception)
	// when the Cache API is unavailable.
	let cache: Cache | null = null;
	try {
		if (typeof caches !== 'undefined') cache = await caches.open(CACHE_NAME);
	} catch {
		cache = null;
	}

	async function warmOne(url: string): Promise<void> {
		try {
			// Skip tiles already present so re-runs and re-renders stay cheap.
			if (cache && (await cache.match(url))) return;
			// Same origin (the instance's proxy): a readable response the map can
			// reuse (no opaque-response pitfalls).
			const resp = await fetch(url, { credentials: 'same-origin' });
			if (cache && resp.ok) await cache.put(url, resp.clone());
		} catch {
			/* ignore individual tile failures */
		}
	}

	for (let i = 0; i < urls.length; i += BATCH) {
		// Stop early if connectivity drops mid-prefetch.
		if (typeof navigator !== 'undefined' && navigator.onLine === false) break;
		await Promise.all(urls.slice(i, i + BATCH).map(warmOne));
		await new Promise((r) => setTimeout(r, BATCH_DELAY_MS));
	}
}

/** Allow a fresh prefetch run (e.g. when the route changes). */
export function resetTilePrefetch(): void {
	warmedKey = null;
}
