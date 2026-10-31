import { writable } from 'svelte/store';

/**
 * Geisterjagd zu Halloween: Ab und zu lugt an einem der Oster-Anker ein Geist
 * hervor und verschwindet nach `SICHTBAR_MS` wieder. Wer ihn antippt, fängt
 * ihn und bekommt Süßes oder Saures; ab `ZIEL` ist man Geisterjäger.
 *
 * Saures ist harmlos und kurz: Fledermäuse fliegen durch, die Spinne lässt
 * sich fallen. Nichts davon berührt die Karte oder eine Eingabe.
 */

export const ZIEL = 13;
export const SICHTBAR_MS = 5000;
/** Der erste Geist kommt bald, damit niemand lange sucht; danach in Abständen. */
export const ERSTER_MS = 2500;
export const ABSTAND_MS: [number, number] = [8000, 16000];

export type Saures = 'schwarm' | 'spinne';

export interface Ausgang {
	text: string;
	saures?: Saures;
}

export const SUESSES: Ausgang[] = [
	{ text: 'Süßes! 🍬 Ein Gummibärchen für die Besatzung.' },
	{ text: 'Süßes! 🍫 Am nächsten Rastplatz gibt es bestimmt Schokoriegel.' },
	{ text: 'Süßes! 🍭 Die Route ist heute garantiert kürbisfrei.' },
	{ text: 'Süßes! 🍪 Der Schließende bekommt das letzte Plätzchen.' },
	{ text: 'Süßes! 🍎 Ein kandierter Apfel – gesund ist was anderes.' },
];

export const SAURES: Ausgang[] = [
	{ text: 'Saures! 🦇 Fledermäuse im Funkverkehr!', saures: 'schwarm' },
	{ text: 'Saures! 🕷️ Wer hat die Spinne geweckt?', saures: 'spinne' },
	{ text: 'Saures! 👻 Buh! Der war nur ein Ablenkungsmanöver.', saures: 'schwarm' },
];

/** Süßes oder Saures, je etwa zur Hälfte. `zufall` liegt in [0, 1). */
export function ausgang(zufall: number): Ausgang {
	const liste = zufall < 0.5 ? SUESSES : SAURES;
	const rest = zufall < 0.5 ? zufall * 2 : (zufall - 0.5) * 2;
	return liste[Math.floor(rest * liste.length)];
}

const SPEICHER = 'convoyplan-geister:';

function lesen(schluessel: string): number {
	try {
		const n = Number(localStorage.getItem(SPEICHER + schluessel));
		return Number.isInteger(n) && n > 0 ? n : 0;
	} catch {
		return 0;
	}
}

function createGeisterStore() {
	const { subscribe, set, update } = writable<{ schluessel: string; gefangen: number }>({ schluessel: '', gefangen: 0 });

	return {
		subscribe,
		laden(schluessel: string) {
			set({ schluessel, gefangen: lesen(schluessel) });
		},
		fangen() {
			update((z) => {
				const gefangen = z.gefangen + 1;
				try {
					localStorage.setItem(SPEICHER + z.schluessel, String(gefangen));
				} catch {
					// Ohne Speicher zählt es bis zum Neuladen.
				}
				return { ...z, gefangen };
			});
		},
	};
}

export const geisterStore = createGeisterStore();
