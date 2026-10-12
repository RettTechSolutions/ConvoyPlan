/**
 * Der nächste Wegpunkt vor einem Fahrzeug und wann es ihn etwa erreicht — für
 * die Blase auf der Karte.
 *
 * Die Ankunft kommt aus dem **Plan**, nicht aus dem momentanen Tempo: Zwischen
 * dem letzten geplanten Zeitpunkt hinter dem Fahrzeug (Abfahrt am vorigen
 * Wegpunkt, sonst Abmarsch) und der geplanten Ankunft am nächsten wird nach der
 * Strecke geteilt; was davon noch vor dem Fahrzeug liegt, kommt auf jetzt
 * drauf. Ein Tempo von der letzten Position stünde an jeder Ampel auf null.
 * Haltezeiten früherer Wegpunkte zählen dabei nicht mit — die liegen hinter dem
 * Anker.
 *
 * Bekannte Grenze: Fährt die Route ein Stück doppelt, kann die Projektion die
 * falsche Vorbeifahrt treffen (wie in `progress.ts`).
 */
import { projectOnRoute, routeLength, type LatLon } from './eta';
import { formatDistance } from './progress';

/** Ab diesem Abstand zur Linie steht das Fahrzeug nicht auf der Route. */
export const ABSEITS_M = 1000;
/** Wie in der Ansage der Wegpunkte: so knapp davor gilt er als erreicht. */
const ERREICHT_M = 40;
/** Ab so viel Abweichung vom Plan steht sie dabei. */
const ABWEICHUNG_MIN = 2;

export interface RoutenHalt {
	name: string;
	/** Entlang der Route (m). */
	m: number;
	an: number | null;
	ab: number | null;
}

interface HaltEingabe {
	name: string;
	lat: number | null;
	lon: number | null;
	planned_arrival: string | null;
	planned_departure: string | null;
}

const zeit = (iso: string | null | undefined) => {
	if (!iso) return null;
	const t = new Date(iso).getTime();
	return Number.isNaN(t) ? null : t;
};

/**
 * Wegpunkte entlang der Route, einmal je Route gerechnet. Das Ziel kommt dazu,
 * wenn nicht schon ein Wegpunkt am Ende steht.
 */
export function routenHalte(
	coords: number[][],
	wegpunkte: HaltEingabe[],
	zielAnkunft: string | null = null,
): RoutenHalt[] {
	if (coords.length < 2) return [];
	const halte: RoutenHalt[] = [];
	for (const w of wegpunkte) {
		if (w.lat == null || w.lon == null) continue;
		const p = projectOnRoute(coords, { lat: w.lat, lon: w.lon });
		if (!p) continue;
		halte.push({ name: w.name, m: p.along, an: zeit(w.planned_arrival), ab: zeit(w.planned_departure) });
	}
	halte.sort((a, b) => a.m - b.m);
	const ende = routeLength(coords);
	const letzter = halte[halte.length - 1];
	if (!letzter || ende - letzter.m > 100) halte.push({ name: 'Ziel', m: ende, an: zeit(zielAnkunft), ab: null });
	return halte;
}

export interface NaechsterHalt {
	name: string;
	restM: number;
	/** Erwartete Ankunft (ms), null ohne geplante Zeiten. */
	eta: number | null;
	/** Geplante Ankunft (ms), wenn bekannt. */
	plan: number | null;
}

export function naechsterHalt(
	coords: number[][],
	halte: RoutenHalt[],
	pos: LatLon,
	abmarsch: string | null,
	jetzt: number,
): NaechsterHalt | null {
	const p = projectOnRoute(coords, pos);
	if (!p || p.offset > ABSEITS_M) return null;
	const i = halte.findIndex((h) => h.m > p.along + ERREICHT_M);
	if (i === -1) return null;
	const ziel = halte[i];

	// Anker: der letzte Zeitpunkt hinter dem Fahrzeug.
	let anker: { m: number; t: number } | null = null;
	for (let k = i - 1; k >= 0 && !anker; k--) {
		const t = halte[k].ab ?? halte[k].an;
		if (t !== null) anker = { m: halte[k].m, t };
	}
	if (!anker) {
		const t = zeit(abmarsch);
		if (t !== null) anker = { m: 0, t };
	}

	let eta: number | null = null;
	if (ziel.an !== null && anker && ziel.m > anker.m && ziel.an >= anker.t) {
		const rest = Math.min(1, Math.max(0, (ziel.m - p.along) / (ziel.m - anker.m)));
		eta = jetzt + rest * (ziel.an - anker.t);
	}
	return { name: ziel.name, restM: ziel.m - p.along, eta, plan: ziel.an };
}

const uhr = (ms: number) => new Date(ms).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });

/** „Nächster: Rosenheim in 2,4 km · an ca. 14:52 (+7 min)". */
export function naechsterHaltText(n: NaechsterHalt): { text: string; warnung: boolean } {
	let text = `Nächster: ${n.name} in ${formatDistance(n.restM)}`;
	let warnung = false;
	if (n.eta !== null) {
		text += ` · an ca. ${uhr(n.eta)}`;
		if (n.plan !== null) {
			const min = Math.round((n.eta - n.plan) / 60000);
			if (Math.abs(min) > ABWEICHUNG_MIN) {
				text += ` (${min > 0 ? '+' : '−'}${Math.abs(min)} min)`;
				warnung = min > 0;
			}
		}
	}
	return { text, warnung };
}
