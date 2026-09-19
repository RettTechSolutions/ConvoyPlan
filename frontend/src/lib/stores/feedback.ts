import { writable } from 'svelte/store';
import type { FeedbackKind } from '$lib/api';

/**
 * Ob der Melde-Dialog offen ist und womit er aufgeht.
 *
 * Ein Store statt einer Prop-Kette, weil der Auslöser und der Dialog nicht
 * beieinander stehen: der Dialog hängt einmal im Org-Layout, die Knöpfe
 * liegen verteilt in der Anwendung (Seitenleiste der Planung, Kopfzeile des
 * Org-Admins). Ohne Store müsste jede Seite dazwischen den Zustand
 * durchreichen, obwohl sie nichts damit zu tun hat.
 *
 * `kind` ist nur der Startwert — im Dialog lässt sich weiterhin umschalten.
 * Wer auf „Fehler melden" klickt, hat aber schon gesagt, worum es geht, und
 * soll das nicht noch einmal ankreuzen müssen.
 */
export interface FeedbackDialog {
	offen: boolean;
	kind: FeedbackKind;
}

const ZU: FeedbackDialog = { offen: false, kind: 'bug' };

function createFeedbackStore() {
	const { subscribe, set } = writable<FeedbackDialog>(ZU);
	return {
		subscribe,
		open: (kind: FeedbackKind = 'bug') => set({ offen: true, kind }),
		close: () => set(ZU),
	};
}

export const feedbackStore = createFeedbackStore();
