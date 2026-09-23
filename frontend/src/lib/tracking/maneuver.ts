/**
 * Das nächste Fahrmanöver für die Tracking-Ansicht im Fahrer-Link.
 *
 * Dieselbe Rechnung wie in der ConvoyPlan Companion-App
 * (`app/src/nav/nextStep.ts` dort), mit denselben Schwellen — damit Browser und
 * App an derselben Stelle dasselbe ansagen. Die Hinweise kommen fertig vom
 * Server (`route_steps`); ihr Meter `m` ist mit derselben Haversine-Summe über
 * die Stützpunkte gemessen wie `distanceAlongRoute()` in `eta.ts`, die beiden
 * Zahlen lassen sich also direkt vergleichen.
 *
 * Gerechnet wird **nur gegen die eigene Position**, nie gegen die
 * Verbandsspitze: „In 300 m rechts" gilt für die Spitze, nicht für das
 * Schlusslicht dahinter, und einen Pfeil befolgt man.
 */
import type { RouteStep } from '$lib/api';
import { haversine, type LatLon } from './eta';
import { formatDistance } from './progress';

/** Ein Manöver gilt erst so weit **hinter** der Stelle als gefahren. */
export const PASSED_M = 20;
/** Darunter steht „Jetzt" statt einer Entfernung. */
export const NOW_M = 30;
/** Weiter weg wird nur die Straße genannt, auf der es weitergeht. */
export const FAR_M = 5_000;

const CONTINUE = 0;
const FINISH = 4;
const VIA = 5;
const ROUNDABOUT = 6;

export interface StepAhead {
	step: RouteStep;
	/** Streckenmeter bis dorthin. Nie negativ. */
	aheadM: number;
	/** Straße, auf der man gerade fährt. */
	currentStreet: string | null;
}

/**
 * Das erste Manöver vor `atM`. „Geradeaus" an einem bloßen Namenswechsel ist
 * keines und trägt nur den Straßennamen weiter.
 */
export function nextStep(steps: readonly RouteStep[], atM: number | null): StepAhead | null {
	if (atM === null || !Number.isFinite(atM)) return null;
	let currentStreet: string | null = null;
	for (const step of steps) {
		if (step.m + PASSED_M <= atM) {
			if (step.street_name) currentStreet = step.street_name;
			continue;
		}
		if (step.sign === CONTINUE) continue;
		return { step, aheadM: Math.max(0, step.m - atM), currentStreet };
	}
	return null;
}

export function stepArrow(sign: number): string {
	switch (sign) {
		case -3: return '↙';
		case -2: return '←';
		case -1: case -7: return '↖';
		case 1: case 7: return '↗';
		case 2: return '→';
		case 3: return '↘';
		case ROUNDABOUT: case -6: return '↻';
		case FINISH: return '⚑';
		case VIA: return '◉';
		case -8: case -98: return '↶';
		case 8: return '↷';
		default: return '↑';
	}
}

const VERBS: Record<number, string> = {
	[-3]: 'Scharf links', [-2]: 'Links abbiegen', [-1]: 'Leicht links',
	[1]: 'Leicht rechts', [2]: 'Rechts abbiegen', [3]: 'Scharf rechts',
	[-7]: 'Links halten', [7]: 'Rechts halten',
	[-8]: 'Wenden', [8]: 'Wenden', [-98]: 'Wenden',
	[-6]: 'Kreisverkehr verlassen', [FINISH]: 'Ziel erreicht', [VIA]: 'Zwischenziel erreicht',
};

/** GraphHoppers Text hat Vorrang; ohne ihn ein eigener aus Vorzeichen und Straße. */
export function stepText(step: RouteStep): string {
	const given = step.text?.trim();
	if (given) return given;
	const street = step.street_name?.trim();
	if (step.sign === ROUNDABOUT) {
		const exit = step.exit_number ? `${step.exit_number}. Ausfahrt` : 'Ausfahrt';
		return `Im Kreisverkehr ${exit}${street ? ` auf ${street}` : ''} nehmen`;
	}
	const verb = VERBS[step.sign] ?? 'Weiter';
	return street && step.sign !== FINISH && step.sign !== VIA ? `${verb} auf ${street}` : verb;
}

/** Punkt auf der Linie bei Streckenmeter `m`; `null` außerhalb. */
export function pointAtM(coords: number[][], m: number): LatLon | null {
	if (m < 0) return null;
	let travelled = 0;
	for (let i = 1; i < coords.length; i++) {
		const a = { lon: coords[i - 1][0], lat: coords[i - 1][1] };
		const b = { lon: coords[i][0], lat: coords[i][1] };
		const len = haversine(a, b);
		if (travelled + len >= m) {
			const t = len > 0 ? (m - travelled) / len : 0;
			return { lat: a.lat + (b.lat - a.lat) * t, lon: a.lon + (b.lon - a.lon) * t };
		}
		travelled += len;
	}
	return Math.abs(m - travelled) < 1 ? { lon: coords.at(-1)![0], lat: coords.at(-1)![1] } : null;
}

export interface Maneuver {
	arrow: string;
	/** „In 400 m", „Jetzt" oder bei fernem Manöver nur die Strecke. */
	distance: string;
	text: string;
	far: boolean;
	/** Die Luftlinie, weil man neben der Route steht — dann wird das dazugesagt. */
	direct: boolean;
	/** Meter bis zum Manöver, wie angezeigt. */
	aheadM: number;
}

/**
 * Die Ankündigung ab der eigenen Position. Neben der Route gilt die größere von
 * Strecke und Luftlinie — die Projektion allein sagte „In 400 m", während noch
 * Kilometer zu fahren sind.
 */
export function maneuverFrom(
	steps: readonly RouteStep[],
	coords: number[][],
	own: LatLon,
	alongM: number | null,
): Maneuver | null {
	const next = nextStep(steps, alongM);
	if (!next) return null;
	const target = pointAtM(coords, next.step.m);
	const directM = target ? haversine(own, target) : null;
	const direct = directM !== null && directM > next.aheadM + 50;
	const aheadM = direct ? directM! : next.aheadM;

	if (aheadM > FAR_M && next.step.sign !== FINISH && next.step.sign !== VIA) {
		return {
			arrow: '↑',
			distance: formatDistance(aheadM),
			text: next.currentStreet ? `Weiter auf ${next.currentStreet}` : 'Der Route folgen',
			far: true, direct, aheadM,
		};
	}
	return {
		arrow: stepArrow(next.step.sign),
		distance: aheadM < NOW_M ? 'Jetzt' : `In ${formatDistance(aheadM)}`,
		text: stepText(next.step),
		far: false, direct, aheadM,
	};
}

/** Eine Zeile der Hinweisliste im Seitenmenü. */
export interface StepRow {
	step: RouteStep;
	arrow: string;
	text: string;
	/** „km 12,4" — die Stelle auf der Route, wie im Roadbook. */
	km: string;
	/**
	 * Gegen die **Verbandsspitze**: gefahren, das nächste oder noch voraus.
	 * `null` ohne Live-Position — dann steht die Liste ohne Stand da, statt
	 * einen zu erfinden.
	 */
	state: 'passed' | 'next' | 'ahead' | null;
	/** Nur beim nächsten: Meter von der Spitze bis dorthin. */
	aheadM: number | null;
}

/**
 * Alle Hinweise der Route als Liste, mit Stand gegen die Spitze.
 *
 * Anders als der Pfeil auf der Karte ist das keine Anweisung, sondern eine
 * Übersicht für Beobachter: Wo steht die Spitze, was kommt als Nächstes? Der
 * Bezugspunkt wird deshalb ausdrücklich genannt („Spitze"), und „Geradeaus"
 * bleibt in der Liste — dort sagt ein Straßenwechsel etwas.
 */
export function stepRows(steps: readonly RouteStep[], frontM: number | null): StepRow[] {
	const known = frontM !== null && Number.isFinite(frontM);
	let nextSeen = false;
	return steps.map((step) => {
		let state: StepRow['state'] = null;
		let aheadM: number | null = null;
		if (known) {
			if (step.m + PASSED_M <= frontM!) state = 'passed';
			else if (!nextSeen) {
				state = 'next';
				aheadM = Math.max(0, step.m - frontM!);
				nextSeen = true;
			} else state = 'ahead';
		}
		return {
			step,
			arrow: stepArrow(step.sign),
			text: stepText(step),
			km: `km ${(step.m / 1000).toLocaleString('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`,
			state,
			aheadM,
		};
	});
}
