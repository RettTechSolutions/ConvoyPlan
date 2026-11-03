import { writable } from 'svelte/store';
import { aktuelleSaison, vorschauSaison, type Saison } from './kalender';

/**
 * Saison-Designs: ein Easter Egg, das nur auf Klick angeht.
 *
 * Der Store sagt, *ob* gerade eine Saison ist und ob sie eingeschaltet wurde;
 * *wo* sie sich zeigt, entscheidet `erlaubt()` — nicht jede Seite verträgt
 * Fledermäuse.
 */

interface Zustand {
	saison: Saison | null;
	aktiv: boolean;
	/** Zeitpunkt des letzten Einschaltens, damit der Rahmen genau dann grüßt. */
	eingeschaltet: number;
}

const SPEICHER = 'convoyplan-saison:';
const VORSCHAU = 'convoyplan-saison-vorschau';

/**
 * Nur Planung, Org-Admin und Admin. Fahrer-Link, Tracking-Ansicht,
 * Share-Link und Statusseite bleiben neutral: dort schaut jemand während der
 * Fahrt oder in einer Störung drauf, und eine Fledermaus über dem Alarm ist
 * nicht witzig.
 */
export function erlaubt(pfad: string): boolean {
	return /^\/o\/[^/]+\/(plan|admin)(\/|$)/.test(pfad) || /^\/admin(\/|$)/.test(pfad);
}

function lesen(schluessel: string): boolean {
	try {
		return localStorage.getItem(SPEICHER + schluessel) === 'an';
	} catch {
		return false;
	}
}

/** `?saison=<id>` bleibt für den Tab bestehen, auch wenn die Adresse wechselt. */
function vorschau(jetzt: Date): Saison | null {
	try {
		const angefragt = new URLSearchParams(location.search).get('saison');
		if (angefragt !== null) {
			if (vorschauSaison(angefragt, jetzt)) sessionStorage.setItem(VORSCHAU, angefragt);
			else sessionStorage.removeItem(VORSCHAU);
		}
		const id = sessionStorage.getItem(VORSCHAU);
		return id ? vorschauSaison(id, jetzt) : null;
	} catch {
		return null;
	}
}

function createSaisonStore() {
	let zustand: Zustand = { saison: null, aktiv: false, eingeschaltet: 0 };

	const { subscribe, set } = writable<Zustand>(zustand, () => {
		if (typeof window === 'undefined') return;
		aktualisieren();
		// Die Saison kann während einer offenen Sitzung beginnen oder enden —
		// und Silvester um 23 Uhr wechselt Schnee zu Feuerwerk.
		const takt = setInterval(aktualisieren, 60_000);
		return () => clearInterval(takt);
	});

	function setzen(neu: Zustand) {
		zustand = neu;
		set(neu);
	}

	function aktualisieren() {
		const jetzt = new Date();
		const saison = vorschau(jetzt) ?? aktuelleSaison(jetzt);
		const aktiv = saison ? lesen(saison.schluessel) : false;
		const alt = zustand.saison;
		if (alt?.schluessel === saison?.schluessel && alt?.partikel === saison?.partikel && zustand.aktiv === aktiv) return;
		setzen({ ...zustand, saison, aktiv });
	}

	function umschalten() {
		const { saison, aktiv } = zustand;
		if (!saison) return;
		try {
			if (aktiv) localStorage.removeItem(SPEICHER + saison.schluessel);
			else localStorage.setItem(SPEICHER + saison.schluessel, 'an');
		} catch {
			// Ohne Speicher gilt die Wahl bis zum Neuladen.
		}
		setzen({ saison, aktiv: !aktiv, eingeschaltet: aktiv ? zustand.eingeschaltet : Date.now() });
	}

	return { subscribe, umschalten };
}

export const saisonStore = createSaisonStore();
