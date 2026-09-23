// Betriebsstofflage eines Fahrzeugs: Verbrauch (l/100 km), Tankvolumen (l)
// und Füllstand (%), wie die Besatzung sie über den Fahrer-Link meldet — aus
// der Companion-App.
//
// Gespeichert wird nur, was gemeldet wurde; Liter im Tank und Reichweite
// rechnet jede Ansicht selbst, wie hinten in `app/services/betriebsstoff.py`.

/** Ab diesem Füllstand wird die Anzeige zur Warnung. */
export const KNAPP_AB_PROZENT = 25;

export interface Betriebsstoff {
	verbrauch: number | null;
	tank: number | null;
	fuellstand: number | null;
	/** Tank bzw. Verbrauch stammen nicht aus der Meldung, sondern aus den Stammdaten. */
	tankAusStammdaten?: boolean;
	verbrauchAusStammdaten?: boolean;
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
 * Nur für Verbrenner: Bei einem E-Fahrzeug stehen in den Stammdaten kWh, und
 * ein Füllstand in Prozent gegen Liter gerechnet ergäbe eine erfundene Zahl.
 * Ohne Meldung bleibt es bei `null` — Stammdaten allein sind keine Lage.
 */
export function mitStammdaten(lage: Betriebsstoff | null, felder: BetriebsstoffFelder): Betriebsstoff | null {
	if (!lage) return null;
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

/** Liter im Tank — `null`, solange Tank oder Füllstand fehlen. */
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

/** Kurzform für die Fahrzeugzeile: Füllstand, sonst Reichweite, sonst Tank. */
export function betriebsstoffKurz(b: Betriebsstoff): string {
	if (b.fuellstand !== null) return `${b.fuellstand} %`;
	const km = reichweiteKm(b);
	if (km !== null) return `${Math.round(km)} km`;
	return b.tank !== null ? `${b.tank} l Tank` : `${zahl(b.verbrauch!)} l/100 km`;
}

/** Die ganze Meldung in Worten — für den Tooltip und Vorlesehilfen. */
export function betriebsstoffTitel(b: Betriebsstoff): string {
	const teile: string[] = [];
	if (b.fuellstand !== null) teile.push(`Füllstand ${b.fuellstand} %`);
	const liter = literImTank(b);
	const stamm = (ja: boolean | undefined) => (ja ? ' (Stammdaten)' : '');
	if (liter !== null) teile.push(`${Math.round(liter)} l von ${zahl(b.tank!)} l${stamm(b.tankAusStammdaten)}`);
	else if (b.tank !== null) teile.push(`Tank ${zahl(b.tank)} l${stamm(b.tankAusStammdaten)}`);
	if (b.verbrauch !== null) teile.push(`Verbrauch ${zahl(b.verbrauch)} l/100 km${stamm(b.verbrauchAusStammdaten)}`);
	const km = reichweiteKm(b);
	if (km !== null) teile.push(`Reichweite etwa ${Math.round(km)} km`);
	return `Betriebsstoff: ${teile.join(' · ')}`;
}
