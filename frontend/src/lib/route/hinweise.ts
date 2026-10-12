/**
 * Was die berechnete Route vom Planer verlangt — gezählt für die Marke am
 * Reiter „Route". Die Ergebnisse stehen nicht mehr im Reiter „Plan"; eine
 * enge Unterführung oder ein fehlender Tankstopp darf deshalb nicht erst
 * auffallen, wenn jemand zufällig hinüberklickt.
 *
 * Gezählt wird, was Handlung oder Prüfung braucht: ein Tankstopp, der noch
 * nicht als Wegpunkt steht, jeder empfohlene Halt, der noch fehlt, und jede
 * Höhen- oder Gewichtsstelle, die nicht `frei` ist. `kritisch` färbt die
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
	/** Wie viele der empfohlenen Halte schon als Wegpunkt stehen. */
	halteGesetzt: number,
): RouteHinweise {
	if (!route) return { anzahl: 0, kritisch: false };
	const fa = route.fuel_analysis;
	const tankstopp = fa?.fuel_stop_needed && !tankstoppGesetzt ? 1 : 0;
	const halte = fa?.duration_halt_needed ? fa.duration_halts.slice(halteGesetzt).length : 0;
	const hoehen = (route.durchfahrtshoehen ?? []).filter((e) => e.stufe !== 'frei');
	const gewicht = (route.gewichtsgrenzen ?? []).filter((e) => e.stufe !== 'frei');
	return {
		anzahl: tankstopp + halte + hoehen.length + gewicht.length,
		kritisch: tankstopp > 0 || hoehen.some((e) => e.stufe === 'eng') || gewicht.some((e) => e.stufe === 'ueberschritten'),
	};
}
