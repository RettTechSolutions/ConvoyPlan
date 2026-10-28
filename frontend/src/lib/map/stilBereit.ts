import type * as maplibregl from 'maplibre-gl';

/**
 * Ruft *fn* einmal auf, sobald der Kartenstil geladen ist — die Stelle für
 * eigene Quellen und Ebenen.
 *
 * Nicht `load`: Das feuert MapLibre erst mit dem ersten Frame, in dem alles
 * geladen ist, und scheitern alle Kacheln (Kachelserver weg, kein Netz), kommt
 * dieser Frame nie. `loaded()` ist dann wahr, aber niemand zeichnet mehr — und
 * Route, Sperrungen, Regionsmaske und Leitstellen fehlten, obwohl sie gar keine
 * Kacheln brauchen. `style.load` hängt nur am Stil, und der ist hier inline.
 * `load` bleibt als zweiter Auslöser, falls `style.load` schon vorbei war.
 */
export function wennStilBereit(map: maplibregl.Map, fn: () => void): void {
	let erledigt = false;
	const los = () => {
		if (erledigt) return;
		erledigt = true;
		map.off('style.load', los);
		map.off('load', los);
		fn();
	};
	map.on('style.load', los);
	map.on('load', los);
	// `isStyleLoaded()` wartet auch auf die Kacheln — als Bedingung im
	// Ereignis taugt es deshalb nicht, nur für den Fall, dass beides schon vorbei ist.
	if (map.isStyleLoaded()) los();
}
