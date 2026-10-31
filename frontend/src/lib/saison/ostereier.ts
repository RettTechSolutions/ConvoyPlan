import { writable } from 'svelte/store';
import { liesListe, schreibListe, wuerfeln, type Lage } from './anker';

/**
 * Ostereiersuche: Zu Ostern liegen in der Planung Eier versteckt, je eines an
 * einem Anker des Tutorials (`data-tour`). Die Anker gibt es in jedem Reiter,
 * und das Tutorial hält sie stabil — wer einen umbenennt, sieht es in
 * `e2e/ostereier.spec.ts`.
 *
 * Wo am Anker ein Ei liegt, hängt vom Jahr ab: nächstes Ostern liegt es
 * woanders.
 */

export const VERSTECKE = [
	'convoy-selector',
	'plan-params',
	'route-actions',
	'waypoints',
	'schedule',
	'vehicles',
	'konto',
	'export',
	'tracking',
	'sidebar-footer',
] as const;

/** Das goldene Ei liegt im Org-Admin — ein Bonus, nicht nötig für „alle gefunden". */
export const GOLDENES_EI = 'gold';

export type Versteck = (typeof VERSTECKE)[number] | typeof GOLDENES_EI;

export type { Lage } from './anker';

export function lage(versteck: Versteck, schluessel: string): Lage {
	return wuerfeln(`${versteck}:${schluessel}`);
}

const SPEICHER = 'convoyplan-ostereier:';

function createEierStore() {
	const { subscribe, set, update } = writable<{ schluessel: string; gefunden: Versteck[] }>({ schluessel: '', gefunden: [] });

	return {
		subscribe,
		laden(schluessel: string) {
			set({ schluessel, gefunden: liesListe<Versteck>(SPEICHER + schluessel).filter((v) => typeof v === 'string') });
		},
		finden(versteck: Versteck) {
			update((z) => {
				if (z.gefunden.includes(versteck)) return z;
				const gefunden = [...z.gefunden, versteck];
				schreibListe(SPEICHER + z.schluessel, gefunden);
				return { ...z, gefunden };
			});
		},
	};
}

export const eierStore = createEierStore();

/** Gefundene Eier ohne das goldene — das zählt extra. */
export function anzahl(gefunden: Versteck[]): number {
	return gefunden.filter((v) => v !== GOLDENES_EI).length;
}
