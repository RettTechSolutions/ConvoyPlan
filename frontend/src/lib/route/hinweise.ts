/**
 * Was die berechnete Route vom Planer verlangt — gezählt für die Marke am
 * Reiter „Route". Die Ergebnisse stehen nicht mehr im Reiter „Plan"; eine
 * enge Unterführung oder ein fehlender Tankstopp darf deshalb nicht erst
 * auffallen, wenn jemand zufällig hinüberklickt.
 *
 * Gezählt wird, was Handlung oder Prüfung braucht: ein Tankstopp, der noch
 * nicht als Wegpunkt steht, jeder empfohlene Halt, der noch fehlt, übernommene
 * Halte, die nach einer neuen Route nicht mehr passen (einmal, nicht je Halt),
 * und jede Höhen- oder Gewichtsstelle, die nicht `frei` ist. `kritisch` färbt die
 * Marke rot: fehlender Tankstopp, enge Durchfahrt, überschrittene Grenze.
 */
import type { DurchfahrtshoeheEntry, FuelAnalysis, GewichtsgrenzeEntry } from '$lib/api';

export interface RouteHinweise {
	anzahl: number;
	kritisch: boolean;
}

export function routeHinweise(
	route: {
		fuel_analysis: FuelAnalysis | null;
		durchfahrtshoehen: DurchfahrtshoeheEntry[] | null;
		gewichtsgrenzen: GewichtsgrenzeEntry[] | null;
	} | null,
	/** Steht schon ein Tankhalt in der Liste? */
	tankstoppGesetzt: boolean,
): RouteHinweise {
	if (!route) return { anzahl: 0, kritisch: false };
	const fa = route.fuel_analysis;
	const tankstopp = fa?.fuel_stop_needed && !tankstoppGesetzt ? 1 : 0;
	// Das Backend rechnet geplante Halte schon heraus: die Liste nennt nur,
	// was fehlt (`fuel._duration_halts`, `geplante_halte`).
	const halte = fa?.duration_halt_needed ? fa.duration_halts.length : 0;
	const neuVerteilen = fa?.neu_verteilen ? 1 : 0;
	const hoehen = (route.durchfahrtshoehen ?? []).filter((e) => e.stufe !== 'frei');
	const gewicht = (route.gewichtsgrenzen ?? []).filter((e) => e.stufe !== 'frei');
	return {
		anzahl: tankstopp + halte + neuVerteilen + hoehen.length + gewicht.length,
		kritisch: tankstopp > 0 || hoehen.some((e) => e.stufe === 'eng') || gewicht.some((e) => e.stufe === 'ueberschritten'),
	};
}
