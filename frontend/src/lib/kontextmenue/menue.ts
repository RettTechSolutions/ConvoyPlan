/**
 * Kontextmenü (rechte Maustaste, Taste „Kontextmenü"/Umschalt+F10, langes
 * Drücken am Telefon).
 *
 * Es gibt genau **ein** Menü, eingehängt im Wurzel-Layout
 * (`Kontextmenue.svelte`); geöffnet wird es über `oeffnen()` oder die Action
 * `kontextmenue`. Ein Store statt einer Komponente je Liste: das Menü muss
 * über allem liegen — Karte, Seitenleiste, Dialoge —, und zwei offene Menüs
 * darf es nicht geben.
 *
 * Das Menü ist eine Abkürzung, kein zweiter Weg: jeder Eintrag ruft dieselbe
 * Funktion wie der Knopf daneben. Was es nur hier gäbe, fände am Telefon
 * niemand.
 */
import { writable } from 'svelte/store';

export type Aktion = {
	label: string;
	/** Ein Zeichen vor dem Text, z. B. ein Emoji wie auf den Knöpfen. */
	icon?: string;
	aktion: () => unknown;
	/** Rot dargestellt — Löschen, Entfernen, Zurücksetzen. */
	gefahr?: boolean;
	/** Ausgegraut; ein Text wird zum Tooltip und sagt, warum. */
	aus?: boolean | string;
	/** Schalter (Häkchen) bzw. Auswahl aus mehreren (Punkt). */
	an?: boolean;
	art?: 'schalter' | 'auswahl';
};
export type Eintrag = Aktion | { trenner: true } | { titel: string };
/** `false`/`null` erlauben bedingte Einträge direkt in der Liste. */
export type Eintraege = (Eintrag | false | null | undefined | '' | 0)[];

export type OffenesMenue = {
	x: number;
	y: number;
	eintraege: Eintrag[];
	/** Bekommt den Fokus zurück, wenn das Menü per Tastatur geschlossen wird. */
	ausloeser: HTMLElement | null;
	/**
	 * Per Tastatur geöffnet: dann steht der Fokus gleich auf dem ersten Eintrag.
	 * Mit der Maus nicht — Chrome zeichnet einen solchen Fokus sichtbar, sobald
	 * vorher nichts Fokussierbares angeklickt wurde (eine Tabellenzelle), und
	 * der erste Eintrag sähe aus wie gewählt.
	 */
	perTastatur: boolean;
};

export const TRENNER = { trenner: true } as const;

export const menue = writable<OffenesMenue | null>(null);
/** Kurze Rückmeldung nach einer Aktion ohne sichtbare Folge (Kopieren). */
export const kurzmeldung = writable<string | null>(null);

export function istAktion(e: Eintrag): e is Aktion {
	return 'aktion' in e;
}

/**
 * Bedingte Einträge entfernen und Trenner aufräumen: keiner am Anfang, am Ende
 * oder doppelt. Ein Titel ohne Aktion darunter fällt mit weg.
 */
export function aufraeumen(roh: Eintraege): Eintrag[] {
	const liste = roh.filter((e): e is Eintrag => !!e);
	const aus: Eintrag[] = [];
	for (const e of liste) {
		if ('trenner' in e && (aus.length === 0 || 'trenner' in aus[aus.length - 1])) continue;
		aus.push(e);
	}
	while (aus.length && !istAktion(aus[aus.length - 1])) aus.pop();
	return aus.some(istAktion) ? aus : [];
}

/** Öffnet das Menü. Ohne einen einzigen Eintrag bleibt es zu (`false`). */
export function oeffnen(
	x: number,
	y: number,
	eintraege: Eintraege,
	ausloeser: HTMLElement | null = null,
	perTastatur = false,
): boolean {
	const liste = aufraeumen(eintraege);
	if (!liste.length) return false;
	menue.set({ x, y, eintraege: liste, ausloeser, perTastatur });
	return true;
}

export function schliessen() {
	menue.set(null);
}

let meldungTimer: ReturnType<typeof setTimeout> | undefined;
export function melden(text: string) {
	kurzmeldung.set(text);
	clearTimeout(meldungTimer);
	meldungTimer = setTimeout(() => kurzmeldung.set(null), 1800);
}

/** Eintrag „… kopieren" mit Rückmeldung — die häufigste Abkürzung überhaupt. */
export function kopieren(label: string, text: string | null | undefined, icon = '📋'): Aktion | false {
	if (!text) return false;
	return {
		label,
		icon,
		aktion: async () => {
			try {
				await navigator.clipboard.writeText(text);
				melden('In die Zwischenablage kopiert');
			} catch {
				melden('Kopieren nicht möglich');
			}
		},
	};
}

/** Koordinaten so, wie man sie am Funk oder in ein Navi gibt: „lat, lon". */
export function koordinatenText(lat: number, lon: number): string {
	return `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
}

/** Die Einträge, die zu jedem Punkt auf der Karte passen. */
export function ortEintraege(lat: number, lon: number): Eintraege {
	return [
		kopieren('Koordinaten kopieren', koordinatenText(lat, lon)),
		{
			label: 'In OpenStreetMap öffnen',
			icon: '🗺',
			aktion: () => window.open(`https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=17/${lat}/${lon}`, '_blank', 'noopener'),
		},
		{
			label: 'In Google Maps öffnen',
			icon: '🌍',
			aktion: () => window.open(`https://www.google.com/maps/search/?api=1&query=${lat},${lon}`, '_blank', 'noopener'),
		},
	];
}

/** Ein Element an eine andere Stelle der Liste schieben (für „Nach oben" & Co.). */
export function verschieben<T>(liste: T[], von: number, nach: number): T[] {
	const ziel = Math.max(0, Math.min(liste.length - 1, nach));
	if (von === ziel || von < 0 || von >= liste.length) return liste;
	const neu = [...liste];
	const [el] = neu.splice(von, 1);
	neu.splice(ziel, 0, el);
	return neu;
}

/**
 * Die vier Einträge zum Umsortieren einer Liste. `speichern` bekommt die neue
 * Reihenfolge — dieselbe Funktion, die auch das Ziehen speichert.
 */
export function reihenfolgeEintraege<T>(
	liste: T[],
	index: number,
	speichern: (neu: T[]) => unknown,
	worte = { hoch: 'Nach oben', runter: 'Nach unten', anfang: 'An den Anfang', ende: 'Ans Ende' },
): Eintraege {
	const erster = index <= 0;
	const letzter = index >= liste.length - 1;
	return [
		{ label: worte.hoch, icon: '↑', aus: erster, aktion: () => speichern(verschieben(liste, index, index - 1)) },
		{ label: worte.runter, icon: '↓', aus: letzter, aktion: () => speichern(verschieben(liste, index, index + 1)) },
		!erster && liste.length > 2 && { label: worte.anfang, icon: '⤒', aktion: () => speichern(verschieben(liste, index, 0)) },
		!letzter && liste.length > 2 && { label: worte.ende, icon: '⤓', aktion: () => speichern(verschieben(liste, index, liste.length - 1)) },
	];
}

/**
 * Wo der Browser sein eigenes Menü behalten soll: in Eingabefeldern
 * (Einfügen, Rechtschreibung), auf markiertem Text (Kopieren) und auf Links
 * (neuer Tab). Wer trotzdem das Browsermenü will, hält Umschalt.
 */
export function browsermenueBehalten(e: MouseEvent, bereich: Element): boolean {
	if (e.shiftKey) return true;
	const ziel = e.target instanceof Element ? e.target : null;
	if (ziel?.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"], a[href]')) return true;
	const auswahl = typeof window !== 'undefined' ? window.getSelection() : null;
	if (auswahl && !auswahl.isCollapsed && auswahl.rangeCount) {
		const r = auswahl.getRangeAt(0);
		if (bereich.contains(r.commonAncestorContainer)) return true;
	}
	return false;
}

/** Ab hier gilt ein ruhender Finger als langes Drücken (wie in MapLibre). */
const LANG_DRUECKEN_MS = 500;
const WACKEL_PX = 10;

/**
 * Svelte-Action: Kontextmenü für ein Element. Die Einträge werden erst beim
 * Öffnen erfragt, also immer zum aktuellen Stand.
 *
 *     <li use:kontextmenue={() => [ … ]}>
 *
 * Verschachtelt gewinnt das innerste Element; liefert es keinen Eintrag, ist
 * das äußere dran.
 */
export function kontextmenue(node: HTMLElement, eintraege: () => Eintraege) {
	let quelle = eintraege;
	let timer: ReturnType<typeof setTimeout> | undefined;
	let start: { x: number; y: number } | null = null;
	let langGedruecktUm = 0;

	function oeffnenBei(x: number, y: number, ziel: EventTarget | null, perTastatur = false): boolean {
		const ausloeser = ziel instanceof HTMLElement ? (ziel.closest<HTMLElement>('button, [tabindex], a') ?? node) : node;
		return oeffnen(x, y, quelle(), ausloeser, perTastatur);
	}

	function onContextmenu(e: MouseEvent) {
		// Das innere Element hat schon geöffnet, oder der Finger eben erst.
		if (e.defaultPrevented) return;
		if (Date.now() - langGedruecktUm < 800) {
			e.preventDefault();
			return;
		}
		if (browsermenueBehalten(e, node)) return;
		let { clientX: x, clientY: y } = e;
		// Per Tastatur ausgelöst: kein Zeiger, also unter das Element.
		const perTastatur = !Number.isFinite(x) || !Number.isFinite(y) || (x === 0 && y === 0);
		if (perTastatur) {
			const r = (document.activeElement instanceof HTMLElement && node.contains(document.activeElement)
				? document.activeElement
				: node
			).getBoundingClientRect();
			x = r.left + 8;
			y = r.bottom;
		}
		if (oeffnenBei(x, y, e.target, perTastatur)) e.preventDefault();
	}

	// iOS Safari kennt kein `contextmenu` beim langen Drücken, Android schon —
	// deshalb ein eigener Zeitgeber und danach das native Ereignis verschlucken.
	function onPointerdown(e: PointerEvent) {
		if (e.pointerType !== 'touch') return;
		abbrechen();
		start = { x: e.clientX, y: e.clientY };
		const ziel = e.target;
		timer = setTimeout(() => {
			timer = undefined;
			if (!start) return;
			if (ziel instanceof Element && ziel.closest('input, textarea, select, a[href]')) return;
			if (oeffnenBei(start.x, start.y, ziel)) langGedruecktUm = Date.now();
		}, LANG_DRUECKEN_MS);
	}
	function onPointermove(e: PointerEvent) {
		if (start && Math.hypot(e.clientX - start.x, e.clientY - start.y) > WACKEL_PX) abbrechen();
	}
	function abbrechen() {
		clearTimeout(timer);
		timer = undefined;
		start = null;
	}
	// Der Klick nach dem Loslassen gehört noch zum langen Drücken.
	function onClick(e: MouseEvent) {
		if (Date.now() - langGedruecktUm < 800) {
			e.preventDefault();
			e.stopPropagation();
		}
	}

	node.addEventListener('contextmenu', onContextmenu);
	node.addEventListener('pointerdown', onPointerdown);
	node.addEventListener('pointermove', onPointermove);
	node.addEventListener('pointerup', abbrechen);
	node.addEventListener('pointercancel', abbrechen);
	node.addEventListener('click', onClick, true);
	return {
		update(neu: () => Eintraege) {
			quelle = neu;
		},
		destroy() {
			abbrechen();
			node.removeEventListener('contextmenu', onContextmenu);
			node.removeEventListener('pointerdown', onPointerdown);
			node.removeEventListener('pointermove', onPointermove);
			node.removeEventListener('pointerup', abbrechen);
			node.removeEventListener('pointercancel', abbrechen);
			node.removeEventListener('click', onClick, true);
		},
	};
}
