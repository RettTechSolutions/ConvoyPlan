/**
 * Etwas an die Kante eines Ankers legen — für Ostereier und Adventstürchen.
 * Gerechnet wird in Fensterkoordinaten (`position: fixed`), weil die Anker in
 * verschiedenen Scrollbereichen stehen.
 */

export interface Lage {
	kante: 'oben' | 'unten' | 'rechts';
	/** Position entlang der Kante, 0…1. */
	anteil: number;
	/** Farbton, für wen es braucht. */
	farbton: number;
}

/** FNV-1a — genügt, um je Jahr eine andere, aber feste Lage zu würfeln. */
export function hash(text: string): number {
	let h = 0x811c9dc5;
	for (let i = 0; i < text.length; i++) {
		h ^= text.charCodeAt(i);
		h = Math.imul(h, 0x01000193);
	}
	return h >>> 0;
}

export function wuerfeln(text: string): Lage {
	const h = hash(text);
	const kanten = ['oben', 'unten', 'rechts'] as const;
	return {
		kante: kanten[h % 3],
		anteil: 0.15 + ((h >>> 4) % 70) / 100,
		farbton: (h >>> 12) % 360,
	};
}

/** Der sichtbare Teil eines Elements: geschnitten mit jedem scrollenden Vorfahren und dem Fenster. */
function sichtbar(el: Element): DOMRect | null {
	const r = el.getBoundingClientRect();
	if (r.width === 0 || r.height === 0) return null;
	let links = Math.max(r.left, 0);
	let oben = Math.max(r.top, 0);
	let rechts = Math.min(r.right, window.innerWidth);
	let unten = Math.min(r.bottom, window.innerHeight);
	for (let p = el.parentElement; p; p = p.parentElement) {
		const s = getComputedStyle(p);
		if (s.overflowX !== 'visible' || s.overflowY !== 'visible') {
			const q = p.getBoundingClientRect();
			links = Math.max(links, q.left);
			oben = Math.max(oben, q.top);
			rechts = Math.min(rechts, q.right);
			unten = Math.min(unten, q.bottom);
		}
	}
	if (rechts - links < 1 || unten - oben < 1) return null;
	return new DOMRect(links, oben, rechts - links, unten - oben);
}

/**
 * Wo ein `groesse` großes Ding auf der Kante seines Ankers liegt — halb
 * darüber hinaus —, oder `null`, wenn seine Mitte gerade nicht im sichtbaren
 * Teil des Ankers läge (anderer Reiter, weggescrollt, Schublade zu).
 */
export function platzieren(el: Element, lage: Lage, groesse: number): { x: number; y: number } | null {
	const rahmen = el.getBoundingClientRect();
	let x: number;
	let y: number;
	if (lage.kante === 'rechts') {
		x = rahmen.right - groesse * 0.6;
		y = rahmen.top + rahmen.height * lage.anteil - groesse / 2;
	} else {
		x = rahmen.left + rahmen.width * lage.anteil - groesse / 2;
		y = lage.kante === 'oben' ? rahmen.top - groesse * 0.45 : rahmen.bottom - groesse * 0.55;
	}
	const s = sichtbar(el);
	const mx = x + groesse / 2;
	const my = y + groesse / 2;
	if (!s || mx < s.left || mx > s.right || my < s.top - groesse || my > s.bottom + groesse) return null;
	return { x, y };
}

/**
 * Ruft `verteilen` sofort, alle 400 ms und bei Scrollen/Größenänderung:
 * Reiterwechsel, aufklappende Karten und Schubladen melden sich nicht.
 * Gibt die Aufräumfunktion zurück.
 */
export function mitverfolgen(verteilen: () => void): () => void {
	verteilen();
	const takt = setInterval(verteilen, 400);
	let geplant = 0;
	const bald = () => {
		cancelAnimationFrame(geplant);
		geplant = requestAnimationFrame(verteilen);
	};
	window.addEventListener('scroll', bald, true);
	window.addEventListener('resize', bald);
	return () => {
		clearInterval(takt);
		cancelAnimationFrame(geplant);
		window.removeEventListener('scroll', bald, true);
		window.removeEventListener('resize', bald);
	};
}

/** Eine gemerkte Liste im Browser (gefundene Eier, geöffnete Türchen). */
export function liesListe<T>(schluessel: string): T[] {
	try {
		const roh = JSON.parse(localStorage.getItem(schluessel) ?? '[]');
		return Array.isArray(roh) ? roh : [];
	} catch {
		return [];
	}
}

export function schreibListe<T>(schluessel: string, liste: T[]) {
	try {
		localStorage.setItem(schluessel, JSON.stringify(liste));
	} catch {
		// Ohne Speicher gilt es bis zum Neuladen.
	}
}
