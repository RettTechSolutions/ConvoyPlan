/**
 * Beschränkungen, die über einen Abschnitt gelten (Durchfahrtshöhe,
 * Gewichtsgrenze). GraphHopper kennt sie je Kante, nicht je Schild — der erste
 * Stützpunkt allein sah aus wie die Stelle selbst. Gemeldet: `maxheight=4` an
 * der Mautzufahrt des Karawankentunnels begann am Ende einer Brücke, und die
 * Brücke stand mit 4,0 m da.
 *
 * Grenze und Text stehen gleich im Backend (`route_steps.abschnitt_text`);
 * wer einen ändert, zieht den anderen mit.
 */

/** Ab dieser Länge ist es ein Abschnitt und kein Punkt. */
export const ABSCHNITT_AB_M = 200;

/** „auf 350 m" bzw. „auf 1,1 km" — leer unter `ABSCHNITT_AB_M`. */
export function abschnittText(laengeM: number | null | undefined): string {
	if (typeof laengeM !== 'number' || !Number.isFinite(laengeM) || laengeM < ABSCHNITT_AB_M) return '';
	if (laengeM < 1000) return `auf ${Math.round(laengeM / 10) * 10} m`;
	return `auf ${(laengeM / 1000).toFixed(1).replace('.', ',')} km`;
}

/** Die Teilstrecke für die Karte — nur als Abschnitt, und nur, wenn die Route sie mitbringt. */
export function abschnittLinie(e: { laenge_m?: number | null; linie?: number[][] | null }): number[][] | undefined {
	if (!abschnittText(e.laenge_m)) return undefined;
	return e.linie && e.linie.length >= 2 ? e.linie : undefined;
}
