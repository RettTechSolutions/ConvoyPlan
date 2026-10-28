import type { Geometry } from 'geojson';

/**
 * Wohin ein Wegpunkt gehört, den jemand durch Ziehen an der Route auf eine
 * andere Straße gesetzt hat.
 *
 * `order_index` ist die Wahrheit (siehe `app/services/waypoint_order.py`), und
 * die nächste Berechnung leitet ihn nicht aus der Route ab. Der neue Punkt muss
 * also gleich an die richtige Stelle der Liste — zwischen die beiden
 * Wegpunkte, zwischen denen das gegriffene Stück der Route liegt. Hinten
 * angehängt führe der Konvoi erst bis zum letzten Wegpunkt und dann zurück.
 *
 * Bezugspunkte sind nur platzierte Wegpunkte mit Lage. Ein vorgeschlagener
 * Halt (`pending_placement`) steht am Listenende, obwohl er in der Mitte
 * liegt, und ordnet sich bei der Berechnung selbst ein.
 */

export type Punkt = { lat: number; lon: number };

export type Listenpunkt = { lat: number | null; lon: number | null; order_index: number; pending_placement?: boolean };

/** Die Linie der Route als [lon, lat], ein MultiLineString hintereinander. */
export function linienpunkte(g: Geometry | null | undefined): number[][] {
	if (!g) return [];
	if (g.type === 'LineString') return g.coordinates as number[][];
	if (g.type === 'MultiLineString') return (g.coordinates as number[][][]).flat();
	return [];
}

/** Meter in einer örtlichen Ebene — für den Vergleich von Abständen genau genug. */
function eben(linie: number[][]): (lon: number, lat: number) => [number, number] {
	const lat0 = linie.length ? linie[Math.floor(linie.length / 2)][1] : 50;
	const kx = 111_320 * Math.cos((lat0 * Math.PI) / 180);
	return (lon, lat) => [lon * kx, lat * 110_540];
}

type Lage = { segment: number; meter: number };

/**
 * Streckenmeter des nächsten Linienpunkts zu *p*, gesucht ab Segment
 * *ab*. Mit *ab* bleibt die Kilometrierung der Wegpunkte monoton: wo die
 * Route ein Stück doppelt fährt (Stichfahrt zu einem Halt), träfe die Suche
 * über die ganze Linie sonst die falsche Vorbeifahrt.
 */
function projiziere(linie: number[][], p: Punkt, ab = 0): Lage | null {
	if (linie.length < 2) return null;
	const xy = eben(linie);
	const [px, py] = xy(p.lon, p.lat);
	let bester: Lage | null = null;
	let besterAbstand = Infinity;
	let bisher = 0;
	let [ax, ay] = xy(linie[0][0], linie[0][1]);
	for (let i = 0; i < linie.length - 1; i++) {
		const [bx, by] = xy(linie[i + 1][0], linie[i + 1][1]);
		const dx = bx - ax;
		const dy = by - ay;
		const laenge = Math.hypot(dx, dy);
		if (i >= ab) {
			const t = laenge > 0 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (laenge * laenge))) : 0;
			const abstand = Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
			if (abstand < besterAbstand) {
				besterAbstand = abstand;
				bester = { segment: i, meter: bisher + t * laenge };
			}
		}
		bisher += laenge;
		ax = bx;
		ay = by;
	}
	return bester;
}

export type Einordnung = {
	/** Der `order_index` für den neuen Wegpunkt; wer dort oder dahinter steht, rückt weiter. */
	order_index: number;
	/** Die Nachbarn auf der Strecke (Wegpunkt, sonst Start bzw. Ziel) — für die Vorschau beim Ziehen. */
	vor: Punkt | null;
	nach: Punkt | null;
};

/**
 * Einordnen eines Punkts, der bei *griff* von der Route gezogen wurde.
 * *wegpunkte* in beliebiger Reihenfolge; sortiert wird nach `order_index`.
 */
export function einordnen(
	linie: number[][],
	wegpunkte: Listenpunkt[],
	griff: Punkt,
	start: Punkt | null = null,
	ziel: Punkt | null = null,
): Einordnung {
	const liste = [...wegpunkte].sort((a, b) => a.order_index - b.order_index);
	const ende = liste.length ? liste[liste.length - 1].order_index + 1 : 0;
	const g = projiziere(linie, griff);
	if (!g) return { order_index: ende, vor: start, nach: ziel };

	// Kilometrierung der Bezugspunkte, in Listenreihenfolge und nie fallend.
	let ab = 0;
	let hoechste = 0;
	let vor: Punkt | null = start;
	let nach: Punkt | null = null;
	let order_index: number | null = null;
	for (const wp of liste) {
		if (wp.pending_placement || wp.lat == null || wp.lon == null) continue;
		const p = { lat: wp.lat, lon: wp.lon };
		const lage = projiziere(linie, p, ab);
		if (!lage) continue;
		ab = lage.segment;
		hoechste = Math.max(hoechste, lage.meter);
		if (hoechste <= g.meter) {
			vor = p;
		} else {
			order_index = wp.order_index;
			nach = p;
			break;
		}
	}
	// Hinter dem letzten Bezugspunkt: ans Ende. Ein wartender Vorschlag dort
	// ordnet sich bei der Berechnung ohnehin selbst ein.
	if (order_index == null) return { order_index: ende, vor, nach: ziel };
	return { order_index, vor, nach };
}
