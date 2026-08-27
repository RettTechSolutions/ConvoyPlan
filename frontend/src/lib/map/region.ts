/**
 * Regionsfokus für alle Karten — aktuell DACH (DE, AT, CH, LI).
 *
 * ConvoyPlan berechnet Routen nur innerhalb der Region, die im
 * GraphHopper-Graph steckt. Damit das auf der Karte sofort sichtbar ist, legen
 * wir eine halbtransparente Maske über alles außerhalb und zeichnen die
 * Außengrenze selbst als dünne Linie.
 *
 * Die Maske ist ein einziges Polygon, das die ganze Welt abdeckt und die
 * Region als Loch (inner ring) ausspart — dadurch braucht es keinen Verschnitt
 * zur Laufzeit und keine zusätzliche Geometrie-Bibliothek.
 *
 * Der Umriss ist bewusst datengetrieben: wer GraphHopper auf eine andere
 * Region stellt, tauscht `static/geo/dach.geojson` und muss hier nichts
 * anfassen. Die Geometrie ist dabei reine Anzeige — verbindlich ist allein,
 * welche Daten GraphHopper geladen hat.
 *
 * Farben und die Helligkeit der Rasterkacheln richten sich nach dem Hell-/
 * Dunkel-Design der App (`themeStore`), damit die Karte nicht als heller Block
 * in der dunklen Oberfläche steht.
 */
import type { Feature, FeatureCollection, MultiPolygon, Position } from 'geojson';
import type * as maplibregl from './maplibre';

export const REGION_URL = '/geo/dach.geojson';
export const REGION_ATTRIBUTION = '© GeoBasis-DE / BKG (dl-de/by-2-0) · Natural Earth';

const MASK_SOURCE = 'region-mask';
const BORDER_SOURCE = 'region-border';
export const MASK_FILL_LAYER = 'region-mask-fill';
export const BORDER_LINE_LAYER = 'region-border-line';

export type MapTheme = 'dark' | 'light';

/**
 * Maskenfarbe je Design. Dunkel wird abgedunkelt, hell entsättigt-vergraut —
 * in beiden Fällen bleibt das Umland erkennbar (Orientierung an Nachbarstädten),
 * tritt aber deutlich hinter der Region zurück.
 */
const MASK_STYLE: Record<MapTheme, { fill: string; fillOpacity: number; border: string; borderOpacity: number }> = {
	dark:  { fill: '#03070c', fillOpacity: 0.68, border: '#7fa8c9', borderOpacity: 0.9 },
	light: { fill: '#8b98a6', fillOpacity: 0.45, border: '#41556b', borderOpacity: 0.75 },
};

/**
 * Rasterkacheln (OSM) je Design. Wir tönen die vorhandenen Kacheln statt einen
 * zweiten, dunklen Kachel-Anbieter einzubinden: keine weitere Abhängigkeit,
 * keine zusätzliche Lizenz-/Attributionsfrage. Vektor-Overlays (Route,
 * Sperrungen, Marker) bleiben unberührt und damit kontraststark.
 */
interface RasterStyle {
	brightnessMax: number;
	saturation: number;
	contrast: number;
}

const RASTER_STYLE: Record<MapTheme, RasterStyle> = {
	dark:  { brightnessMax: 0.72, saturation: -0.18, contrast: 0 },
	light: { brightnessMax: 1, saturation: 0, contrast: 0 },
};

/** Weltring (im Uhrzeigersinn), aus dem die Region ausgestanzt wird. */
const WORLD_RING: Position[] = [
	[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85],
];

const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] };

let _outline: Feature<MultiPolygon> | null = null;
let _pending: Promise<Feature<MultiPolygon>> | null = null;

/** Lädt den Regionsumriss einmalig und cacht ihn für die Lebensdauer der Seite. */
export function loadRegionOutline(): Promise<Feature<MultiPolygon>> {
	if (_outline) return Promise.resolve(_outline);
	if (_pending) return _pending;
	_pending = fetch(REGION_URL)
		.then((res) => {
			if (!res.ok) throw new Error('Regionsgrenze konnte nicht geladen werden');
			return res.json() as Promise<Feature<MultiPolygon>>;
		})
		.then((f) => {
			_outline = f;
			return f;
		});
	_pending.catch(() => { _pending = null; });
	return _pending;
}

/**
 * Baut aus der Regionsgrenze das Gegenstück: Welt minus Region.
 *
 * Jeder äußere Ring der Region (Festland + Inseln) wird zum Loch im
 * Weltpolygon. Löcher im Umriss selbst — fremdstaatliche Enklaven wie Campione
 * d'Italia — gehören nicht zur Region und werden deshalb als eigene Polygone
 * wieder maskiert. Der aktuelle DACH-Umriss enthält keine solchen Löcher; der
 * Zweig bleibt, damit ein anderer Umriss ohne Codeänderung funktioniert.
 */
export function buildMask(outline: Feature<MultiPolygon>): FeatureCollection {
	const holes: Position[][] = [];
	const enclaves: Position[][][] = [];
	for (const polygon of outline.geometry.coordinates) {
		const [outer, ...inner] = polygon;
		if (outer) holes.push(outer);
		for (const ring of inner) enclaves.push([ring]);
	}
	const geometry: MultiPolygon = {
		type: 'MultiPolygon',
		coordinates: [[WORLD_RING, ...holes], ...enclaves],
	};
	return { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry }] };
}

/**
 * Legt Maske und Grenzlinie auf die Karte. Die Layer werden sofort (leer)
 * angelegt und erst danach befüllt — so liegen alle später hinzugefügten Layer
 * (Route, Sperrungen, Leitstellen) garantiert darüber.
 *
 * Schlägt das Laden fehl, bleibt die Karte ohne Maske voll nutzbar.
 */
export function addRegionMask(map: maplibregl.Map, theme: MapTheme): void {
	const style = MASK_STYLE[theme];
	map.addSource(MASK_SOURCE, { type: 'geojson', data: EMPTY });
	map.addLayer({
		id: MASK_FILL_LAYER,
		type: 'fill',
		source: MASK_SOURCE,
		paint: { 'fill-color': style.fill, 'fill-opacity': style.fillOpacity },
	});
	// Namensnennung an die Quelle hängen: MapLibres AttributionControl sammelt
	// sie automatisch ein, sodass die dl-de/by-2-0-Auflage der BKG-Daten neben
	// der OSM-Nennung erscheint — ohne eigenes UI.
	map.addSource(BORDER_SOURCE, {
		type: 'geojson',
		data: EMPTY,
		attribution: REGION_ATTRIBUTION,
	});
	map.addLayer({
		id: BORDER_LINE_LAYER,
		type: 'line',
		source: BORDER_SOURCE,
		layout: { 'line-join': 'round', 'line-cap': 'round' },
		paint: {
			'line-color': style.border,
			'line-opacity': style.borderOpacity,
			'line-width': ['interpolate', ['linear'], ['zoom'], 4, 1, 10, 2.5],
		},
	});

	loadRegionOutline()
		.then((outline) => {
			// Die Karte kann zwischenzeitlich zerstört worden sein (Seitenwechsel).
			const mask = map.getSource(MASK_SOURCE) as maplibregl.GeoJSONSource | undefined;
			const border = map.getSource(BORDER_SOURCE) as maplibregl.GeoJSONSource | undefined;
			mask?.setData(buildMask(outline));
			border?.setData(outline);
		})
		.catch(() => {
			// Ohne Maske ist die Karte weiterhin bedienbar — kein Blocker.
		});
}

/**
 * Färbt Maske, Grenze und Rasterkacheln auf das aktuelle Design um.
 * `rasterLayer` ist die id des Basemap-Rasterlayers (überall 'osm').
 */
export function applyMapTheme(map: maplibregl.Map, theme: MapTheme, rasterLayer = 'osm'): void {
	const style = MASK_STYLE[theme];
	if (map.getLayer(MASK_FILL_LAYER)) {
		map.setPaintProperty(MASK_FILL_LAYER, 'fill-color', style.fill);
		map.setPaintProperty(MASK_FILL_LAYER, 'fill-opacity', style.fillOpacity);
	}
	if (map.getLayer(BORDER_LINE_LAYER)) {
		map.setPaintProperty(BORDER_LINE_LAYER, 'line-color', style.border);
		map.setPaintProperty(BORDER_LINE_LAYER, 'line-opacity', style.borderOpacity);
	}
	if (map.getLayer(rasterLayer)) {
		const raster = RASTER_STYLE[theme];
		map.setPaintProperty(rasterLayer, 'raster-brightness-max', raster.brightnessMax);
		map.setPaintProperty(rasterLayer, 'raster-saturation', raster.saturation);
		map.setPaintProperty(rasterLayer, 'raster-contrast', raster.contrast);
	}
}
