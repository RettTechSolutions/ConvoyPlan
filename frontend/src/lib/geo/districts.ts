// Zuständigkeitsgebiete für die Leitstellen-Gebietsauswahl im gesamten
// Routing-Raum: deutsche Landkreise und kreisfreie Städte, österreichische
// politische Bezirke, Schweizer Kantone und Liechtenstein.
//
// Die Ebenen sind bewusst nicht einheitlich — in DE und AT hängt die
// Zuständigkeit an der Kreis-/Bezirksebene, in der Schweiz am Kanton.
//
// Gebaut von `scripts/geo/build_gebiete.py`, gebündelt unter
// static/geo/gebiete.geojson. Im Code bleibt es bei „district“, weil das
// API- und Datenbankfeld `district_codes` heißt; in der Oberfläche steht
// „Gebiet“, denn ein Kanton ist kein Landkreis.

/** Länder des abgedeckten Routing-Raums. */
export type DistrictCountry = 'DE' | 'AT' | 'CH' | 'LI';

export const COUNTRY_LABEL: Record<DistrictCountry, string> = {
	DE: 'Deutschland',
	AT: 'Österreich',
	CH: 'Schweiz',
	LI: 'Liechtenstein',
};

export interface DistrictProps {
	/** ISO-Land + Landesschlüssel: "DE-08115", "AT-322", "CH-040", "LI-000". */
	code: string;
	name: string;
	country: DistrictCountry;
	/** Bundesland (DE/AT). Für Kantone und Liechtenstein null — dort gibt es
	 *  unterhalb des Bundes keine weitere Verwaltungsebene. */
	region: string | null;
}

export type DistrictFeature = GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon, DistrictProps>;

export const DISTRICTS_ATTRIBUTION =
	'© GeoBasis-DE / BKG (dl-de/by-2-0) · © Statistik Austria (CC BY 4.0) · © EuroGeographics / Eurostat';
export const DISTRICTS_URL = '/geo/gebiete.geojson';

let _cache: GeoJSON.FeatureCollection | null = null;
let _byCode: Record<string, DistrictFeature> | null = null;
let _pending: Promise<{ fc: GeoJSON.FeatureCollection; byCode: Record<string, DistrictFeature> }> | null = null;

/**
 * Lädt die Gebietsgrenzen einmalig und cacht sie für die Lebensdauer der Seite.
 * Liefert die FeatureCollection und einen Index code -> Feature.
 */
export function loadDistricts(): Promise<{ fc: GeoJSON.FeatureCollection; byCode: Record<string, DistrictFeature> }> {
	if (_cache && _byCode) return Promise.resolve({ fc: _cache, byCode: _byCode });
	if (_pending) return _pending;
	_pending = (async () => {
		const res = await fetch(DISTRICTS_URL);
		if (!res.ok) throw new Error('Gebietsdaten konnten nicht geladen werden');
		const fc = (await res.json()) as GeoJSON.FeatureCollection;
		const byCode: Record<string, DistrictFeature> = {};
		for (const f of fc.features as DistrictFeature[]) {
			if (f.properties?.code) byCode[f.properties.code] = f;
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

/** Anzeigezeile unter dem Namen: "Baden-Württemberg · Deutschland" bzw. "Schweiz". */
export function districtSubtitle(props: DistrictProps): string {
	const country = COUNTRY_LABEL[props.country] ?? props.country;
	return props.region ? `${props.region} · ${country}` : country;
}
