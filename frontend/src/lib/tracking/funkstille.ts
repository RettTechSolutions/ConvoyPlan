/**
 * Funkstille: ein Fahrzeug, das fuhr und seit `FUNKSTILLE_MS` keine Position
 * mehr geschickt hat.
 *
 * „Keine neue Position" allein ist kein Alarm. Das Telefon meldet über
 * `watchPosition` nur, wenn es sich bewegt, und ein Tracker schläft nach fünf
 * Minuten Stand — ein Fahrzeug am Rastplatz schweigt also zu Recht. Wer bei
 * seiner letzten Position aber noch fuhr (`FAHRT_KMH`), liefert laufend neue;
 * bleiben die aus, ist das Gerät weg: Funkloch, Akku, Absturz. Ohne Tempo
 * (Handeingabe, manche Geräte) lässt sich das nicht unterscheiden, und es gibt
 * keine Warnung. Angekommene Fahrzeuge zählen nicht.
 *
 * Gemessen wird ab dem Eintreffen beim Betrachter, nicht ab `recorded_at` —
 * dessen Uhr ist die des Servers oder des Trackers, und eine falsch gehende
 * Uhr am Führungsrechner ergäbe sonst Alarme oder verschluckte sie. Nur für
 * Positionen, die schon beim Laden da waren, gilt `recorded_at`, und auch das
 * höchstens bis jetzt.
 */

export const FUNKSTILLE_MS = 3 * 60_000;
/** Ab diesem Tempo bei der letzten Position gilt das Fahrzeug als fahrend. */
export const FAHRT_KMH = 5;

interface PositionLike {
	recorded_at: string;
	speed_kmh: number | null;
}

export interface Gehoert {
	recorded_at: string;
	/** Wann diese Position beim Betrachter ankam (ms). */
	t: number;
}

/** Hält fest, wann jede Position zuletzt neu war. */
export function zuletztGehoert(
	vorher: ReadonlyMap<string, Gehoert>,
	positionen: ReadonlyMap<string, PositionLike>,
	jetzt: number,
): Map<string, Gehoert> {
	const neu = new Map<string, Gehoert>();
	for (const [id, p] of positionen) {
		const alt = vorher.get(id);
		if (alt && alt.recorded_at === p.recorded_at) {
			neu.set(id, alt);
		} else if (alt) {
			neu.set(id, { recorded_at: p.recorded_at, t: jetzt });
		} else {
			const zeit = new Date(p.recorded_at).getTime();
			neu.set(id, { recorded_at: p.recorded_at, t: Number.isNaN(zeit) ? jetzt : Math.min(zeit, jetzt) });
		}
	}
	return neu;
}

/** Fahrzeuge in Funkstille, mit dem Zeitpunkt ihrer letzten Position — die älteste zuerst. */
export function funkstille(
	gehoert: ReadonlyMap<string, Gehoert>,
	positionen: ReadonlyMap<string, PositionLike>,
	statusVon: (id: string) => string,
	jetzt: number,
): { id: string; seit: number; kmh: number }[] {
	const out: { id: string; seit: number; kmh: number }[] = [];
	for (const [id, p] of positionen) {
		const g = gehoert.get(id);
		if (!g || jetzt - g.t < FUNKSTILLE_MS) continue;
		if (p.speed_kmh == null || p.speed_kmh < FAHRT_KMH) continue;
		if (statusVon(id) === 'arrived') continue;
		out.push({ id, seit: g.t, kmh: p.speed_kmh });
	}
	return out.sort((a, b) => a.seit - b.seit);
}
