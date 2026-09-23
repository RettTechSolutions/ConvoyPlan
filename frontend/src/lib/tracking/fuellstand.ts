// Füllstand von Tank bzw. Akku eines Fahrzeugs im Verband.
//
// Gemeldet wird in **Prozent**, nicht in Litern: die Besatzung liest eine
// Tanknadel ab („halb", „Reserve"), und ein E-Fahrzeug zeigt ohnehin Prozent.
// Liter, Kilowattstunden und Reichweite rechnet erst die Anzeige aus den
// Stammdaten — die Meldung selbst bleibt eine Aussage darüber, was die
// Besatzung gesehen hat. Die Grenzen stehen gleichlautend hinten in
// `app/services/fuellstand.py`.
//
// Eigene Datei statt einer Ergänzung von `staerke.ts`: jene wird in ein
// anderes Repo übernommen und dort auf Abweichung geprüft.

export const MIN_PROZENT = 0;
export const MAX_PROZENT = 100;

/** Darunter wird der Füllstand hervorgehoben — Zeit, einen Tankstopp einzuplanen. */
export const WARNSCHWELLE_PROZENT = 25;

/** Die Stellungen einer Tankanzeige, wie man sie ohne Rechnen abliest. */
export const SCHNELLWAHL: readonly { label: string; prozent: number }[] = [
	{ label: 'Reserve', prozent: 10 },
	{ label: '¼', prozent: 25 },
	{ label: '½', prozent: 50 },
	{ label: '¾', prozent: 75 },
	{ label: 'Voll', prozent: 100 },
];

/** Eine eingegangene Meldung, wie der Live-Kanal sie verteilt. */
export interface FuellstandMeldung {
	prozent: number;
	gemeldet_at: string | null;
}

/**
 * Was eine Anzeige braucht: die Stammdaten des Fahrzeugs und die Meldung.
 * In der öffentlichen Nutzlast stehen beide im Fahrzeug, in der angemeldeten
 * liegen die Stammdaten unter `cv.vehicle` — der Aufrufer legt sie zusammen.
 */
export interface FuellstandFelder {
	propulsion?: string | null;
	tank_capacity_l?: number | null;
	current_fuel_l?: number | null;
	fuel_consumption_l100km?: number | null;
	battery_capacity_kwh?: number | null;
	current_charge_kwh?: number | null;
	consumption_kwh_100km?: number | null;
	fuellstand_ist_prozent?: number | null;
	fuellstand_gemeldet_at?: string | null;
}

export interface FuellstandAnzeige {
	/** Die Zeile für die Liste, z. B. `Tank 50 % · ≈ 40 l · ≈ 320 km`. */
	text: string;
	/** Beschriftung für Maus und Screenreader. */
	titel: string;
	/** Füllstand in Prozent, soweit er sich angeben lässt. */
	prozent: number | null;
	/** Unter der Warnschwelle. */
	warnung: boolean;
	/** Von der Besatzung gemeldet — sonst nur der eingetragene Stand aus der Planung. */
	gemeldet: boolean;
}

/**
 * Eine Eingabe auf das Erlaubte bringen: ganze Zahl zwischen 0 und 100, oder
 * `null`, wenn nichts Brauchbares dasteht. Leer ist **nicht** 0 — 0 hieße „leer
 * gefahren" und wäre eine Meldung.
 */
export function klemmProzent(wert: unknown): number | null {
	if (wert == null || wert === '') return null;
	const n = Number(wert);
	if (!Number.isFinite(n)) return null;
	return Math.min(MAX_PROZENT, Math.max(MIN_PROZENT, Math.round(n)));
}

/** Die Felder mit der neuesten Live-Meldung obenauf. */
export function mitMeldung<T extends FuellstandFelder>(felder: T, meldung: FuellstandMeldung | null | undefined): T {
	if (!meldung) return felder;
	return { ...felder, fuellstand_ist_prozent: meldung.prozent, fuellstand_gemeldet_at: meldung.gemeldet_at };
}

const positiv = (n: number | null | undefined): n is number => typeof n === 'number' && n > 0;

/** Deutsche Schreibweise mit Dezimalkomma. */
function zahl(n: number, stellen = 0): string {
	return n.toLocaleString('de-DE', { maximumFractionDigits: stellen });
}

function uhrzeit(iso: string | null | undefined): string | null {
	if (!iso) return null;
	const d = new Date(iso);
	if (Number.isNaN(d.getTime())) return null;
	return d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
}

/**
 * Die Anzeige eines Fahrzeugs, oder `null`, wenn es weder eine Meldung noch
 * einen eingetragenen Stand gibt — dann steht in der Liste gar nichts, statt
 * einer leeren Hülle, die nach Information aussieht.
 *
 * Eine Meldung schlägt den eingetragenen Stand: der stammt aus der Planung und
 * ist nach den ersten Kilometern überholt. Umgekehrt wird ein eingetragener
 * Stand ausdrücklich als „laut Planung" gekennzeichnet, damit ihn niemand für
 * eine Meldung von unterwegs hält.
 */
export function fuellstandAnzeige(f: FuellstandFelder): FuellstandAnzeige | null {
	const elektrisch = f.propulsion === 'electric';
	const art = elektrisch ? 'Akku' : 'Tank';
	const einheit = elektrisch ? 'kWh' : 'l';
	const kapazitaet = elektrisch ? f.battery_capacity_kwh : f.tank_capacity_l;
	const verbrauch = elektrisch ? f.consumption_kwh_100km : f.fuel_consumption_l100km;
	const eingetragen = elektrisch ? f.current_charge_kwh : f.current_fuel_l;
	// Bruchteile einer Kilowattstunde sind beim Akku noch eine Aussage, ein
	// Zehntelliter im Tank nicht.
	const stellen = elektrisch ? 1 : 0;

	const gemeldet = f.fuellstand_ist_prozent;
	if (gemeldet != null) {
		// Auf null/undefined geprüft, nicht auf Wahrheitswert: 0 % ist „leer"
		// und damit gerade die Meldung, die niemand übersehen darf.
		const teile = [`${art} ${gemeldet} %`];
		if (positiv(kapazitaet)) {
			const menge = (gemeldet / 100) * kapazitaet;
			teile.push(`≈ ${zahl(menge, stellen)} ${einheit}`);
			if (positiv(verbrauch)) teile.push(`≈ ${zahl((menge / verbrauch) * 100)} km`);
		}
		const um = uhrzeit(f.fuellstand_gemeldet_at);
		const warnung = gemeldet < WARNSCHWELLE_PROZENT;
		return {
			text: teile.join(' · '),
			titel: `${art} ${gemeldet} % gemeldet${um ? ` um ${um}` : ''}${warnung ? ' — unter ¼, Tankstopp einplanen' : ''}`,
			prozent: gemeldet,
			warnung,
			gemeldet: true,
		};
	}

	if (eingetragen != null) {
		let prozent: number | null = null;
		let text: string;
		if (positiv(kapazitaet)) {
			prozent = Math.round((eingetragen / kapazitaet) * 100);
			text = `${art} ${zahl(eingetragen, 1)} von ${zahl(kapazitaet, 1)} ${einheit} (${prozent} %)`;
		} else {
			text = `${art} ${zahl(eingetragen, 1)} ${einheit}`;
		}
		const warnung = prozent != null && prozent < WARNSCHWELLE_PROZENT;
		return {
			text: `${text} · laut Planung`,
			titel: `Noch keine Meldung — eingetragener Stand aus der Planung${warnung ? ', unter ¼' : ''}`,
			prozent,
			warnung,
			gemeldet: false,
		};
	}

	return null;
}
