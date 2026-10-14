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

export function klappbar(node: HTMLElement, id: string | undefined) {
	if (!id) return;
	const kopf = node.querySelector<HTMLElement>(':scope > .section-header');
	const titel = kopf?.querySelector<HTMLElement>(':scope > strong');
	if (!kopf || !titel) return;

	let zu = gemerkt(id) ?? window.matchMedia(SCHMAL).matches;

	kopf.classList.add('klapp-kopf');
	titel.classList.add('klapp-titel');
	titel.setAttribute('role', 'button');
	titel.tabIndex = 0;

	const zeigen = () => {
		node.classList.toggle('klapp-zu', zu);
		titel.setAttribute('aria-expanded', String(!zu));
	};
	const umschalten = () => {
		zu = !zu;
		merken(id, zu);
		zeigen();
	};
	const taste = (e: KeyboardEvent) => {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			umschalten();
		}
	};

	titel.addEventListener('click', umschalten);
	titel.addEventListener('keydown', taste);
	zeigen();

	return {
		destroy() {
			titel.removeEventListener('click', umschalten);
			titel.removeEventListener('keydown', taste);
		},
	};
}
