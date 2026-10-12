/**
 * Vermerk am Wegpunkt, wenn ein fälliger Halt in ihm aufgeht — „Tankhalt + TH".
 *
 * Die Halte-Empfehlung legt einen Technischen Halt, der kurz vor oder nach
 * einem geplanten Halt fällig wäre, mit diesem zusammen (Backend:
 * `fuel.halteplan`). Die WOLKE-Prüfung entfällt damit nicht, sie findet dort
 * statt — und das muss am Wegpunkt stehen. Derselbe Text steht auf dem
 * Ausdruck (`pdf.halt_vermerk`); wer ihn hier ändert, ändert ihn dort mit.
 */
import type { FuelAnalysis, HaltKind, ZusammengelegterHalt } from '$lib/api';

const LANG: Record<HaltKind, string> = {
	tech: 'Technischer Halt (WOLKE)',
	break: 'Lenkpause',
	daily_rest: 'Tagesruhezeit',
};
const KURZ: Record<HaltKind, string> = { tech: '+ TH', break: '+ Lenkpause', daily_rest: '+ Tagesruhe' };

/** Je Wegpunkt-ID die Halte, die in ihm aufgehen. */
export function vermerkeJeWegpunkt(fa: FuelAnalysis | null | undefined): Map<string, ZusammengelegterHalt[]> {
	const out = new Map<string, ZusammengelegterHalt[]>();
	for (const z of fa?.zusammengelegt ?? []) {
		if (!z.waypoint_id) continue;
		out.set(z.waypoint_id, [...(out.get(z.waypoint_id) ?? []), z]);
	}
	return out;
}

/** „zugleich Technischer Halt (WOLKE), empfohlen 30 min" — die Dauer nur, wenn der Halt kürzer geplant ist. */
export function vermerkText(eintraege: ZusammengelegterHalt[], haltMin: number): string {
	if (eintraege.length === 0) return '';
	const teile = eintraege.map((z) => LANG[z.kind] + (z.duration_min > haltMin ? `, empfohlen ${z.duration_min} min` : ''));
	return `zugleich ${teile.join('; ')}`;
}

export function vermerkKurz(z: ZusammengelegterHalt): string {
	return KURZ[z.kind];
}
