// Mannschaftsstärke (Personalstärke) eines Fahrzeugs, geschrieben
// `Führer/Unterführer/Mannschaften//Gesamt` — also etwa `0/1/8//9`.
//
// Einzige Quelle für beide Seiten: den Fahrer-Link, über den die Besatzung
// meldet, und die Tracking-Ansicht, in der die Führung abliest. Die
// Gesamtzahl wird hier gerechnet, nie übertragen — dasselbe gilt hinten in
// `app/services/staerke.py`.

/** Grenze je Rolle, gleichlautend zum Backend (`staerke.MAX_JE_ROLLE`). */
export const MAX_JE_ROLLE = 99;

/** Was in der Anzeige steht, solange nichts gemeldet ist. */
export const OHNE_MELDUNG = '–/–/–';

export interface Staerke {
	fuehrer: number;
	unterfuehrer: number;
	mannschaften: number;
}

/** Die sechs Zahlen, wie Backend-Nutzlasten sie führen. */
export interface StaerkeFelder {
	staerke_soll_fuehrer?: number | null;
	staerke_soll_unterfuehrer?: number | null;
	staerke_soll_mannschaften?: number | null;
	staerke_ist_fuehrer?: number | null;
	staerke_ist_unterfuehrer?: number | null;
	staerke_ist_mannschaften?: number | null;
}

function aus(
	fuehrer: number | null | undefined,
	unterfuehrer: number | null | undefined,
	mannschaften: number | null | undefined,
): Staerke | null {
	// Alle drei leer heißt „nicht angegeben". Eine einzelne Null ist dagegen
	// eine Aussage, deshalb wird hier auf null/undefined geprüft und nicht auf
	// Wahrheitswert — `0 || null` hätte eine Meldung verschluckt.
	if (fuehrer == null && unterfuehrer == null && mannschaften == null) return null;
	return { fuehrer: fuehrer ?? 0, unterfuehrer: unterfuehrer ?? 0, mannschaften: mannschaften ?? 0 };
}

/** Sollstärke aus der Planung, oder `null` wenn keine geplant ist. */
export function sollAus(v: StaerkeFelder): Staerke | null {
	return aus(v.staerke_soll_fuehrer, v.staerke_soll_unterfuehrer, v.staerke_soll_mannschaften);
}

/** Gemeldete Stärke, oder `null` wenn noch nichts gemeldet wurde. */
export function istAus(v: StaerkeFelder): Staerke | null {
	return aus(v.staerke_ist_fuehrer, v.staerke_ist_unterfuehrer, v.staerke_ist_mannschaften);
}

export function gesamt(s: Staerke): number {
	return s.fuehrer + s.unterfuehrer + s.mannschaften;
}

/** `0/1/8//9`, oder `–/–/–` wenn nichts vorliegt. */
export function formatStaerke(s: Staerke | null): string {
	if (!s) return OHNE_MELDUNG;
	return `${s.fuehrer}/${s.unterfuehrer}/${s.mannschaften}//${gesamt(s)}`;
}

/**
 * Weicht die Meldung vom Soll ab?
 *
 * Eine fehlende Meldung ist **keine** Abweichung — unbekannt ist nicht
 * dasselbe wie zu wenig, und die Führung soll die beiden Fälle nicht
 * gleichgesetzt vorfinden.
 */
export function weichtAb(soll: Staerke | null, ist: Staerke | null): boolean {
	if (!soll || !ist) return false;
	return (
		soll.fuehrer !== ist.fuehrer ||
		soll.unterfuehrer !== ist.unterfuehrer ||
		soll.mannschaften !== ist.mannschaften
	);
}

/** Beschriftung für Maus und Screenreader — die Aussage darf nicht allein in der Farbe stecken. */
export function staerkeTitel(soll: Staerke | null, ist: Staerke | null): string {
	if (!ist) {
		return soll
			? `Noch keine Stärkemeldung — Soll ${formatStaerke(soll)}`
			: 'Noch keine Stärkemeldung';
	}
	if (weichtAb(soll, ist)) {
		return `Abweichung vom Soll: gemeldet ${formatStaerke(ist)}, Soll ${formatStaerke(soll)}`;
	}
	return soll
		? `Stärke ${formatStaerke(ist)} — wie geplant`
		: `Stärke ${formatStaerke(ist)}`;
}

/** Gesamtstärke eines Verbands: Summe der Meldungen plus die Zahl der Schweigenden. */
export function verbandsStaerke(fahrzeuge: StaerkeFelder[]): { gemeldet: Staerke; offen: number } {
	const gemeldet: Staerke = { fuehrer: 0, unterfuehrer: 0, mannschaften: 0 };
	let offen = 0;
	for (const f of fahrzeuge) {
		const ist = istAus(f);
		if (!ist) {
			offen++;
			continue;
		}
		gemeldet.fuehrer += ist.fuehrer;
		gemeldet.unterfuehrer += ist.unterfuehrer;
		gemeldet.mannschaften += ist.mannschaften;
	}
	return { gemeldet, offen };
}
