// Deutsche Landkreise / kreisfreie Städte (Kreisgrenzen) für die
// Leitstellen-Gebietsauswahl. Daten: © GeoBasis-DE / BKG (dl-de/by-2-0),
// vereinfacht und gebündelt unter static/geo/landkreise.geojson.

export interface DistrictProps {
	krs_code: string;
	krs_name: string;
	lan_name: string;
}

export type DistrictFeature = GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon, DistrictProps>;

export const DISTRICTS_ATTRIBUTION = '© GeoBasis-DE / BKG (dl-de/by-2-0)';
export const DISTRICTS_URL = '/geo/landkreise.geojson';

let _cache: GeoJSON.FeatureCollection | null = null;
let _byCode: Record<string, DistrictFeature> | null = null;
let _pending: Promise<{ fc: GeoJSON.FeatureCollection; byCode: Record<string, DistrictFeature> }> | null = null;

/**
 * Lädt die Kreisgrenzen einmalig und cacht sie für die Lebensdauer der Seite.
 * Liefert die FeatureCollection und einen Index krs_code -> Feature.
 */
export function loadDistricts(): Promise<{ fc: GeoJSON.FeatureCollection; byCode: Record<string, DistrictFeature> }> {
	if (_cache && _byCode) return Promise.resolve({ fc: _cache, byCode: _byCode });
	if (_pending) return _pending;
	_pending = (async () => {
		const res = await fetch(DISTRICTS_URL);
		if (!res.ok) throw new Error('Landkreis-Daten konnten nicht geladen werden');
		const fc = (await res.json()) as GeoJSON.FeatureCollection;
		const byCode: Record<string, DistrictFeature> = {};
		for (const f of fc.features as DistrictFeature[]) {
			if (f.properties?.krs_code) byCode[f.properties.krs_code] = f;
		}
		_cache = fc;
		_byCode = byCode;
		return { fc, byCode };
	})();
	try {
		return _pending;
	} finally {
		// allow retry on failure
		_pending.catch(() => { _pending = null; });
	}
}
