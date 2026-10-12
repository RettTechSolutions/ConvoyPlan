/**
 * Kartenausschnitt für den Knopf „Konvoi": alle Fahrzeuge mit Position.
 *
 * Eine Position bleibt liegen, wenn ein Gerät nicht mehr sendet. Ein Fahrzeug,
 * das vor Stunden in der Unterkunft aufgehört hat, zöge den Ausschnitt sonst über
 * die halbe Republik — deshalb zählen nur aktuelle Positionen, solange es welche
 * gibt. Gibt es keine, sind alle besser als gar keine.
 */

/** Wie alt eine Position sein darf, um noch zum Konvoi zu zählen. */
export const AKTUELL_MS = 30 * 60_000;

export interface Ortung {
	lat: number;
	lon: number;
	recorded_at: string;
}

/** `[[west, süd], [ost, nord]]`, wie `fitBounds` ihn nimmt; `null` ohne Position. */
export type Ausschnitt = [[number, number], [number, number]];

export function konvoiAusschnitt(positionen: Iterable<Ortung>, jetzt = Date.now()): Ausschnitt | null {
	const alle = [...positionen].filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
	if (alle.length === 0) return null;
	const aktuell = alle.filter((p) => jetzt - Date.parse(p.recorded_at) <= AKTUELL_MS);
	const punkte = aktuell.length > 0 ? aktuell : alle;
	const lons = punkte.map((p) => p.lon);
	const lats = punkte.map((p) => p.lat);
	return [
		[Math.min(...lons), Math.min(...lats)],
		[Math.max(...lons), Math.max(...lats)],
	];
}
