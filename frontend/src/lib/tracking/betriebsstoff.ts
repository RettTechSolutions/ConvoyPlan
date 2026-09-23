// Betriebsstofflage eines Fahrzeugs: Verbrauch (l/100 km), Tankvolumen (l)
// und Füllstand (%), wie die Besatzung sie über den Fahrer-Link meldet — aus
// der Companion-App.
//
// Ein E-Fahrzeug meldet nur den Ladestand in Prozent. Kapazität und Verbrauch
// kommen dann aus seinen kWh-Stammdaten, und alles, was hier „Tank" und
// „Verbrauch" heißt, steht für diese Lage in kWh und kWh/100 km. Die Rechnung
// ist dieselbe — sie darf nur nie Liter und kWh mischen.
//
// Gespeichert wird nur, was gemeldet wurde; Liter im Tank und Reichweite
// rechnet jede Ansicht selbst, wie hinten in `app/services/betriebsstoff.py`.

/** Grenzen einer Meldung, gleichlautend zum Backend (`services/betriebsstoff.py`). */
export const MAX_VERBRAUCH = 150;
export const MAX_TANK = 1500;
export const MAX_FUELLSTAND = 100;

/** Ab diesem Füllstand wird die Anzeige zur Warnung. */
export const KNAPP_AB_PROZENT = 25;

export interface Betriebsstoff {
	verbrauch: number | null;
	tank: number | null;
	fuellstand: number | null;
	/** Tank bzw. Verbrauch stammen nicht aus der Meldung, sondern aus den Stammdaten. */
	tankAusStammdaten?: boolean;
	verbrauchAusStammdaten?: boolean;
	/** E-Fahrzeug: `tank` ist die Akkukapazität in kWh, `verbrauch` in kWh/100 km. */
	elektrisch?: boolean;
}

/** Die Felder, wie Backend-Nutzlasten sie führen. */
export interface BetriebsstoffFelder {
	betriebsstoff_verbrauch?: number | null;
	betriebsstoff_tank?: number | null;
	betriebsstoff_fuellstand?: number | null;
	// Kraftstoff-Stammdaten des Fahrzeugs — das „Soll" zur Meldung.
	propulsion?: string;
	tank_capacity_l?: number | null;
	fuel_consumption_l100km?: number | null;
	// Akku-Stammdaten eines E-Fahrzeugs.
	battery_capacity_kwh?: number | null;
	consumption_kwh_100km?: number | null;
}

/** Die Meldung aus den Feldern — `null`, wenn nichts gemeldet ist. */
export function betriebsstoffAus(felder: BetriebsstoffFelder): Betriebsstoff | null {
	const verbrauch = felder.betriebsstoff_verbrauch ?? null;
	const tank = felder.betriebsstoff_tank ?? null;
	const fuellstand = felder.betriebsstoff_fuellstand ?? null;
	if (verbrauch === null && tank === null && fuellstand === null) return null;
	return { verbrauch, tank, fuellstand };
}

/**
 * Füllt, was die Meldung offen lässt, aus den Stammdaten auf — so rechnet die
 * Reichweite auch, wenn die Besatzung nur den Füllstand meldet.
 *
 * Bei einem E-Fahrzeug kommen Kapazität und Verbrauch **immer** aus den
 * kWh-Stammdaten: Die Meldung trägt dort nur den Ladestand, und Liter, die
 * doch darin stünden, gegen kWh gerechnet ergäben eine erfundene Reichweite.
 * Ohne Meldung bleibt es bei `null` — Stammdaten allein sind keine Lage.
 */
export function mitStammdaten(lage: Betriebsstoff | null, felder: BetriebsstoffFelder): Betriebsstoff | null {
	if (!lage) return null;
	if (felder.propulsion === 'electric') {
		// Ohne Ladestand sagt die Meldung eines E-Fahrzeugs nichts, was die
		// Zeile tragen könnte — Stammdaten allein sind keine Lage.
		if (lage.fuellstand === null) return null;
		const kapazitaet = felder.battery_capacity_kwh || null;
		const verbrauch = felder.consumption_kwh_100km || null;
		return {
			fuellstand: lage.fuellstand,
			tank: kapazitaet,
			verbrauch,
			tankAusStammdaten: kapazitaet !== null,
			verbrauchAusStammdaten: verbrauch !== null,
			elektrisch: true,
		};
	}
	if ((felder.propulsion ?? 'combustion') !== 'combustion') return lage;
	const stammTank = felder.tank_capacity_l ?? null;
	const stammVerbrauch = felder.fuel_consumption_l100km ?? null;
	return {
		...lage,
		tank: lage.tank ?? stammTank,
		verbrauch: lage.verbrauch ?? stammVerbrauch,
		tankAusStammdaten: lage.tank === null && stammTank !== null,
		verbrauchAusStammdaten: lage.verbrauch === null && stammVerbrauch !== null,
	};
}

/** Liter im Tank (E-Fahrzeug: kWh im Akku) — `null`, solange Tank oder Füllstand fehlen. */
export function literImTank(b: Betriebsstoff): number | null {
	if (b.tank === null || b.fuellstand === null) return null;
	return (b.tank * b.fuellstand) / 100;
}

/** Reichweite in Kilometern — `null`, solange eine der drei Angaben fehlt. */
export function reichweiteKm(b: Betriebsstoff): number | null {
	const liter = literImTank(b);
	if (liter === null || b.verbrauch === null || b.verbrauch <= 0) return null;
	return (liter / b.verbrauch) * 100;
}

/** Ob der Füllstand eine Warnung verdient. Ohne Füllstand: nein — unbekannt ist nicht knapp. */
export function istKnapp(b: Betriebsstoff): boolean {
	return b.fuellstand !== null && b.fuellstand <= KNAPP_AB_PROZENT;
}

const zahl = (n: number) => n.toLocaleString('de-DE', { maximumFractionDigits: 1 });

/** Einheiten und Wörter je Antrieb. */
function begriffe(b: Betriebsstoff) {
	return b.elektrisch
		? { was: 'Akku', stand: 'Ladestand', inhalt: 'Akku', einheit: 'kWh', verbrauch: 'kWh/100 km' }
		: { was: 'Betriebsstoff', stand: 'Füllstand', inhalt: 'Tank', einheit: 'l', verbrauch: 'l/100 km' };
}

/** Kurzform für die Fahrzeugzeile: Füllstand, sonst Reichweite, sonst Tank. */
export function betriebsstoffKurz(b: Betriebsstoff): string {
	if (b.fuellstand !== null) return `${b.fuellstand} %`;
	const km = reichweiteKm(b);
	if (km !== null) return `${Math.round(km)} km`;
	const w = begriffe(b);
	return b.tank !== null ? `${b.tank} ${w.einheit} ${w.inhalt}` : `${zahl(b.verbrauch!)} ${w.verbrauch}`;
}

/** Die ganze Meldung in Worten — für den Tooltip und Vorlesehilfen. */
export function betriebsstoffTitel(b: Betriebsstoff): string {
	const w = begriffe(b);
	const teile: string[] = [];
	if (b.fuellstand !== null) teile.push(`${w.stand} ${b.fuellstand} %`);
	const inhalt = literImTank(b);
	const stamm = (ja: boolean | undefined) => (ja ? ' (Stammdaten)' : '');
	if (inhalt !== null) teile.push(`${Math.round(inhalt)} ${w.einheit} von ${zahl(b.tank!)} ${w.einheit}${stamm(b.tankAusStammdaten)}`);
	else if (b.tank !== null) teile.push(`${w.inhalt} ${zahl(b.tank)} ${w.einheit}${stamm(b.tankAusStammdaten)}`);
	if (b.verbrauch !== null) teile.push(`Verbrauch ${zahl(b.verbrauch)} ${w.verbrauch}${stamm(b.verbrauchAusStammdaten)}`);
	const km = reichweiteKm(b);
	if (km !== null) teile.push(`Reichweite etwa ${Math.round(km)} km`);
	return `${w.was}: ${teile.join(' · ')}`;
}
