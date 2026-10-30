import { writable } from 'svelte/store';

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

export interface Lage {
	kante: 'oben' | 'unten' | 'rechts';
	/** Position entlang der Kante, 0…1. */
	anteil: number;
	/** Farbton des Eis. */
	farbton: number;
}

/** FNV-1a — genügt, um je Jahr eine andere, aber feste Lage zu würfeln. */
function hash(text: string): number {
	let h = 0x811c9dc5;
	for (let i = 0; i < text.length; i++) {
		h ^= text.charCodeAt(i);
		h = Math.imul(h, 0x01000193);
	}
	return h >>> 0;
}

export function lage(versteck: Versteck, schluessel: string): Lage {
	const h = hash(`${versteck}:${schluessel}`);
	const kanten = ['oben', 'unten', 'rechts'] as const;
	return {
		kante: kanten[h % 3],
		anteil: 0.15 + ((h >>> 4) % 70) / 100,
		farbton: (h >>> 12) % 360,
	};
}

const SPEICHER = 'convoyplan-ostereier:';

function lesen(schluessel: string): Versteck[] {
	try {
		const roh = JSON.parse(localStorage.getItem(SPEICHER + schluessel) ?? '[]');
		return Array.isArray(roh) ? roh.filter((v): v is Versteck => typeof v === 'string') : [];
	} catch {
		return [];
	}
}

function createEierStore() {
	const { subscribe, set, update } = writable<{ schluessel: string; gefunden: Versteck[] }>({ schluessel: '', gefunden: [] });

	return {
		subscribe,
		laden(schluessel: string) {
			set({ schluessel, gefunden: lesen(schluessel) });
		},
		finden(versteck: Versteck) {
			update((z) => {
				if (z.gefunden.includes(versteck)) return z;
				const gefunden = [...z.gefunden, versteck];
				try {
					localStorage.setItem(SPEICHER + z.schluessel, JSON.stringify(gefunden));
				} catch {
					// Ohne Speicher gilt der Fund bis zum Neuladen.
				}
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
