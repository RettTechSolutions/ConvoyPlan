// Kacheln kommen von der eigenen Instanz, nicht direkt vom Kachelserver:
// /api/tiles ist ein Proxy mit Cache (backend/app/services/tile_proxy.py).
// So sieht der Kachelserver nur die Instanz, nicht die IP jedes Nutzers.
import { getBaseUrl } from '$lib/api/client';

/** Basis der Kachel-URLs; absolut, weil MapLibre relative Kachel-URLs nicht auflöst. */
export function tileBase(): string {
	const base = getBaseUrl() || (typeof location !== 'undefined' ? location.origin : '');
	return `${base}/api/tiles`;
}

/** Vorlage für MapLibre-Rasterquellen. */
export function tileUrlTemplate(): string {
	return `${tileBase()}/{z}/{x}/{y}.png`;
}

export const TILE_ATTRIBUTION = '© OpenStreetMap contributors';
