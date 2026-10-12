/**
 * Abstand eines Fahrzeugs zu seinem Vordermann — für die Blase auf der Karte.
 *
 * Vordermann ist das Fahrzeug davor in der **Marschfolge** (`position`), nicht
 * das, das gerade zufällig voraus fährt: Die Frage der Führung ist, ob der
 * Verband zusammenbleibt. Hat der unmittelbare Vordermann keine Position (kein
 * Gerät), zählt das nächste davor, das eine hat — und die Blase nennt, wen.
 *
 * Gemessen wird entlang der Route, nicht in Luftlinie; in einer Kurve wäre die
 * sonst zu kurz. Die beiden Positionen sind selten gleich alt — bei 80 km/h
 * sind fünf Sekunden über 100 m —, deshalb wird die ältere mit ihrem Tempo
 * fortgeschrieben, aber nur bis `FORTSCHREIBEN_MAX_S`. Darüber wäre die Zahl
 * geraten, und die Blase sagt das statt einer Zahl.
 *
 * Gegen die Sollabstände (15/50/100 m) wird nicht gewarnt: Sie hängen an der
 * Straßenklasse, die hier niemand kennt, und liegen in der Größenordnung der
 * GPS-Ungenauigkeit. Gewarnt wird erst ab `ABRISS_M` — da ist der Verband
 * abgerissen, bei welcher Straßenklasse auch immer.
 */
import { projectOnRoute } from './eta';
import { ABSEITS_M } from './naechsterhalt';
import { formatDistance } from './progress';

export const FORTSCHREIBEN_MAX_S = 60;
/** Ab diesem Abstand zum Vordermann gilt der Verband als abgerissen. */
export const ABRISS_M = 1000;

export interface Streckenstand {
	along: number;
	/** Zeitpunkt der Position (ms). */
	t: number;
	/** m/s, 0 ohne Angabe. */
	v: number;
}

interface PositionLike {
	lat: number;
	lon: number;
	speed_kmh: number | null;
	recorded_at: string;
}

/** Alle Live-Positionen einmal auf die Route gelegt; abseits Stehende fehlen. */
export function streckenstaende(coords: number[][], positionen: Map<string, PositionLike>): Map<string, Streckenstand> {
	const out = new Map<string, Streckenstand>();
	for (const [id, p] of positionen) {
		const proj = projectOnRoute(coords, p);
		const t = new Date(p.recorded_at).getTime();
		if (!proj || proj.offset > ABSEITS_M || Number.isNaN(t)) continue;
		out.set(id, { along: proj.along, t, v: Math.max(0, (p.speed_kmh ?? 0) / 3.6) });
	}
	return out;
}

export interface Vordermann {
	name: string;
	/** Positiv: Vordermann voraus. Negativ: er liegt zurück. null: Positionen zu weit auseinander. */
	abstandM: number | null;
}

export function vordermann(
	reihenfolge: { id: string; name: string }[],
	staende: Map<string, Streckenstand>,
	id: string,
): Vordermann | null {
	const ich = staende.get(id);
	const i = reihenfolge.findIndex((f) => f.id === id);
	if (!ich || i <= 0) return null;
	for (let k = i - 1; k >= 0; k--) {
		const er = staende.get(reihenfolge[k].id);
		if (!er) continue;
		const dt = (ich.t - er.t) / 1000;
		if (Math.abs(dt) > FORTSCHREIBEN_MAX_S) return { name: reihenfolge[k].name, abstandM: null };
		// Den älteren Stand auf den Zeitpunkt des jüngeren fortschreiben.
		const erAlong = dt > 0 ? er.along + er.v * dt : er.along;
		const ichAlong = dt < 0 ? ich.along - ich.v * dt : ich.along;
		return { name: reihenfolge[k].name, abstandM: erAlong - ichAlong };
	}
	return null;
}

/**
 * „Vordermann Akkon 10/1: 350 m", „… 1,4 km – Abriss", „… 200 m dahinter",
 * „… Positionen nicht gleichzeitig". Ein überholter Vordermann ist kein
 * Abriss — der Verband ist dann nur umsortiert.
 */
export function vordermannText(v: Vordermann): { text: string; warnung: boolean } {
	const vorn = `Vordermann ${v.name}:`;
	if (v.abstandM === null) return { text: `${vorn} Positionen nicht gleichzeitig`, warnung: false };
	if (v.abstandM < 0) return { text: `${vorn} ${formatDistance(-v.abstandM)} dahinter`, warnung: false };
	if (v.abstandM > ABRISS_M) return { text: `${vorn} ${formatDistance(v.abstandM)} – Abriss`, warnung: true };
	return { text: `${vorn} ${formatDistance(v.abstandM)}`, warnung: false };
}

/**
 * Wie lange der Abstand über `ABRISS_M` bleiben muss, bevor das Banner kommt.
 * Eine Ampel trennt einen Verband oft für einen Umlauf, und ein Alarm, der bei
 * jeder Ampel anschlägt, wird bald nicht mehr gelesen.
 */
export const ABRISS_NACH_MS = 60_000;

/**
 * Seit wann jedes Fahrzeug ununterbrochen mehr als `ABRISS_M` hinter seinem
 * Vordermann liegt (Uhr des Betrachters, nicht der Positionen). Wer darunter
 * fällt, beginnt von vorn — auch, wenn sich kein Abstand bestimmen lässt
 * („Positionen nicht gleichzeitig"): Ein Alarm auf eine geschätzte Zahl hin
 * wäre schlimmer als einer, der eine Minute später kommt.
 */
export function abrissSeit(
	vorher: ReadonlyMap<string, number>,
	abstaende: ReadonlyMap<string, Vordermann | null>,
	jetzt: number,
): Map<string, number> {
	const seit = new Map<string, number>();
	for (const [id, v] of abstaende) {
		if (v?.abstandM != null && v.abstandM > ABRISS_M) seit.set(id, vorher.get(id) ?? jetzt);
	}
	return seit;
}

/** Fahrzeuge, deren Abriss lange genug anhält, um gemeldet zu werden — der älteste zuerst. */
export function abrisse(seit: ReadonlyMap<string, number>, jetzt: number): string[] {
	return [...seit].filter(([, t]) => jetzt - t >= ABRISS_NACH_MS).sort((a, b) => a[1] - b[1]).map(([id]) => id);
}
