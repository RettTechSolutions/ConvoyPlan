import './klappbar.css';

/**
 * Macht eine Karte (`.section` mit `.section-header > strong`) zusammenklappbar:
 * Der Titel wird zum Schalter, zugeklappt bleibt nur die Kopfzeile stehen.
 *
 * Als Action und nicht als Komponente, weil die Karten im Admin-Portal schon
 * gebaut sind — mit eigenen Knöpfen in der Kopfzeile und Stilen je Seite. Die
 * Action fügt deshalb **keine** Knoten ein (die gehören Svelte), sie setzt nur
 * Klassen und Attribute.
 *
 * Auf dem Telefon starten die Karten zugeklappt — sonst ist der System-Reiter
 * eine Wand aus neun Karten, und wer zur letzten will, scrollt an allen vorbei.
 * Am Schreibtisch starten sie offen. Was jemand einmal auf- oder zugeklappt
 * hat, merkt sich der Browser je `id`; das schlägt den Standard.
 *
 * `{ id, offen: true }` startet auch am Telefon offen — für die eine
 * Arbeitskarte eines Reiters (Mitglieder, GPS-Freigaben …): zugeklappt wäre
 * sie nur ein Tipp mehr bis zur Arbeit.
 *
 * Der Titel ist das erste `strong` der Kopfzeile, auch eine Ebene tiefer
 * (`<div><strong>Name</strong> <span class="marke">…</span></div>`): So bleibt
 * ein Abzeichen neben dem Namen zugeklappt sichtbar, etwa an Trackern.
 *
 * Ein Knopf in der Kopfzeile mit `data-klapp-oeffnen` klappt die Karte auf,
 * bevor er wirkt — für Knöpfe, deren Ergebnis *in* der Karte erscheint
 * (Vorschau). Alle anderen lassen den Zustand, wie er ist.
 */

export const SCHMAL = '(max-width: 768px)';
const SCHLUESSEL = 'convoyplan.klappbar.';

function gemerkt(id: string): boolean | null {
	try {
		const wert = localStorage.getItem(SCHLUESSEL + id);
		return wert === null ? null : wert === 'zu';
	} catch {
		return null;
	}
}

function merken(id: string, zu: boolean): void {
	try {
		localStorage.setItem(SCHLUESSEL + id, zu ? 'zu' : 'auf');
	} catch {
		/* privates Fenster o. ä. — dann eben nur bis zum Neuladen */
	}
}

export type KlappAngabe = string | { id: string; offen?: boolean } | undefined;

export function klappbar(node: HTMLElement, angabe: KlappAngabe) {
	if (!angabe) return;
	const { id, offen = false } = typeof angabe === 'string' ? { id: angabe } : angabe;
	const kopf = node.querySelector<HTMLElement>(':scope > .section-header');
	const titel = kopf?.querySelector<HTMLElement>(':scope > strong, :scope > :first-child > strong:first-child');
	if (!kopf || !titel) return;

	let zu = gemerkt(id) ?? (!offen && window.matchMedia(SCHMAL).matches);

	kopf.classList.add('klapp-kopf');
	titel.classList.add('klapp-titel');
	titel.setAttribute('role', 'button');
	titel.tabIndex = 0;

	const zeigen = () => {
		node.classList.toggle('klapp-zu', zu);
		titel.setAttribute('aria-expanded', String(!zu));
	};
	const setzen = (wert: boolean) => {
		zu = wert;
		merken(id, zu);
		zeigen();
	};
	const umschalten = () => setzen(!zu);
	const taste = (e: KeyboardEvent) => {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			umschalten();
		}
	};
	const kopfKlick = (e: MouseEvent) => {
		if (zu && (e.target as Element | null)?.closest('[data-klapp-oeffnen]')) setzen(false);
	};

	titel.addEventListener('click', umschalten);
	titel.addEventListener('keydown', taste);
	kopf.addEventListener('click', kopfKlick);
	zeigen();

	return {
		destroy() {
			titel.removeEventListener('click', umschalten);
			titel.removeEventListener('keydown', taste);
			kopf.removeEventListener('click', kopfKlick);
		},
	};
}
