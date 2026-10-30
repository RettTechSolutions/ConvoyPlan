/**
 * Wann welche Saison ist — ohne Store, ohne DOM, damit
 * `e2e/saison-kalender.spec.ts` die Grenzen direkt prüfen kann.
 *
 * Gerechnet wird in der Ortszeit des Browsers: Halloween ist, wenn es beim
 * Planer Halloween ist, nicht in UTC.
 */

export type SaisonId =
	| 'fasching'
	| 'notruf'
	| 'april'
	| 'ostern'
	| 'wiesn'
	| 'halloween'
	| 'advent'
	| 'winter';

export type Partikel = 'konfetti' | 'schnee' | 'fledermaeuse' | 'feuerwerk' | null;

export interface Saison {
	id: SaisonId;
	/**
	 * Unter diesem Namen merkt sich der Browser die Wahl. Er trägt das Jahr,
	 * in dem das Fenster beginnt: `winter-2026` gilt bis zum 6.1.2027, und
	 * wer Halloween 2026 eingeschaltet hat, bekommt 2027 wieder nur den Knopf.
	 */
	schluessel: string;
	name: string;
	symbol: string;
	partikel: Partikel;
	/** Hinweise beim Einschalten, nacheinander je einige Sekunden. */
	gruss: string[];
}

type Vorlage = Omit<Saison, 'schluessel'>;

const VORLAGEN: Record<SaisonId, Vorlage> = {
	fasching: { id: 'fasching', name: 'Fasching', symbol: '🎭', partikel: 'konfetti', gruss: ['Helau und Alaaf! Die Marschfolge bleibt trotzdem, wie sie ist.'] },
	notruf: {
		id: 'notruf', name: '112', symbol: '🚨', partikel: null,
		gruss: ['Heute ist der Europäische Tag des Notrufs 112. Danke an alle in den Leitstellen!'],
	},
	april: {
		id: 'april', name: 'Route', symbol: '🃏', partikel: null,
		gruss: ['Route wird über Sylt berechnet …', 'April, April! 🃏 Deine Route ist unverändert.'],
	},
	ostern: { id: 'ostern', name: 'Ostern', symbol: '🐣', partikel: null, gruss: ['Frohe Ostern! In der Planung sind 10 Eier versteckt — viel Spaß beim Suchen.'] },
	wiesn: { id: 'wiesn', name: 'Wiesn', symbol: '🥨', partikel: null, gruss: ["O'zapft is! Der Fahrer bleibt bei Spezi."] },
	halloween: { id: 'halloween', name: 'Halloween', symbol: '🎃', partikel: 'fledermaeuse', gruss: ['Süßes oder Saures? Die Route ist jedenfalls nicht verhext.'] },
	advent: { id: 'advent', name: 'Advent', symbol: '🎄', partikel: 'schnee', gruss: ['Frohe Weihnachten! Schneeketten bitte trotzdem selbst einplanen.'] },
	winter: { id: 'winter', name: 'Winter', symbol: '❄️', partikel: 'schnee', gruss: ['Guten Rutsch und eine gute Fahrt ins neue Jahr!'] },
};

export const SAISON_IDS = Object.keys(VORLAGEN) as SaisonId[];

const EHRENAMT_GRUSS = 'Heute ist der Internationale Tag des Ehrenamts. Danke an alle, die ihre Freizeit in Fahrzeugen und Wachen verbringen!';

/** Ostersonntag im gregorianischen Kalender (anonymer Algorithmus nach Meeus/Jones/Butcher). */
export function ostersonntag(jahr: number): Date {
	const a = jahr % 19;
	const b = Math.floor(jahr / 100);
	const c = jahr % 100;
	const d = Math.floor(b / 4);
	const e = b % 4;
	const f = Math.floor((b + 8) / 25);
	const g = Math.floor((b - f + 1) / 3);
	const h = (19 * a + b - d - g + 15) % 30;
	const i = Math.floor(c / 4);
	const k = c % 4;
	const l = (32 + 2 * e + 2 * i - h - k) % 7;
	const m = Math.floor((a + 11 * h + 22 * l) / 451);
	const monat = Math.floor((h + l - 7 * m + 114) / 31);
	const tag = ((h + l - 7 * m + 114) % 31) + 1;
	return new Date(jahr, monat - 1, tag);
}

/**
 * Oktoberfest: beginnt am Samstag nach dem 15. September und endet am ersten
 * Sonntag im Oktober — fällt der auf den 1. oder 2., wird bis zum 3. Oktober
 * verlängert.
 */
export function wiesn(jahr: number): { von: Date; bis: Date } {
	const von = new Date(jahr, 8, 16);
	while (von.getDay() !== 6) von.setDate(von.getDate() + 1);
	const bis = new Date(jahr, 9, 1);
	while (bis.getDay() !== 0) bis.setDate(bis.getDate() + 1);
	if (bis.getDate() < 3) bis.setDate(3);
	return { von, bis };
}

/** Tage addieren über das Datum statt über Millisekunden — sonst verrutscht es an der Zeitumstellung. */
function plusTage(datum: Date, tage: number): Date {
	return new Date(datum.getFullYear(), datum.getMonth(), datum.getDate() + tage);
}

/** `von` und `bis` sind ganze Tage, beide eingeschlossen. */
function zwischen(jetzt: Date, von: Date, bis: Date): boolean {
	const heute = new Date(jetzt.getFullYear(), jetzt.getMonth(), jetzt.getDate()).getTime();
	return heute >= von.getTime() && heute <= bis.getTime();
}

function saison(id: SaisonId, startjahr: number, anders: Partial<Vorlage> = {}): Saison {
	return { ...VORLAGEN[id], ...anders, schluessel: `${id}-${startjahr}` };
}

/** Silvester 23 Uhr bis Neujahr 1 Uhr: Feuerwerk statt Schnee. */
function istSilvesternacht(jetzt: Date): boolean {
	const m = jetzt.getMonth();
	const t = jetzt.getDate();
	const h = jetzt.getHours();
	return (m === 11 && t === 31 && h >= 23) || (m === 0 && t === 1 && h < 1);
}

/**
 * Die Saison zu einem Zeitpunkt, oder `null`. Eintägige Anlässe gehen den
 * längeren vor: der 11. Februar kann im Fasching liegen, der 1. April in
 * der Osterwoche.
 */
export function aktuelleSaison(jetzt: Date): Saison | null {
	const j = jetzt.getFullYear();
	const m = jetzt.getMonth() + 1;
	const t = jetzt.getDate();

	if (m === 2 && t === 11) return saison('notruf', j);
	if (m === 4 && t === 1) return saison('april', j);

	const ostern = ostersonntag(j);
	// Weiberfastnacht bis Faschingsdienstag; am Aschermittwoch ist alles vorbei.
	if (zwischen(jetzt, plusTage(ostern, -52), plusTage(ostern, -47))) return saison('fasching', j);
	// Gründonnerstag bis Ostermontag.
	if (zwischen(jetzt, plusTage(ostern, -3), plusTage(ostern, 1))) return saison('ostern', j);

	const w = wiesn(j);
	if (zwischen(jetzt, w.von, w.bis)) return saison('wiesn', j);

	if (zwischen(jetzt, new Date(j, 9, 30), new Date(j, 10, 1))) return saison('halloween', j);

	if (m === 12 && t <= 26) {
		return saison('advent', j, t === 5 ? { gruss: [EHRENAMT_GRUSS] } : {});
	}

	const silvester = istSilvesternacht(jetzt) ? { partikel: 'feuerwerk' as const } : {};
	if (m === 12 && t >= 27) return saison('winter', j, silvester);
	if (m === 1 && t <= 6) return saison('winter', j - 1, silvester);

	return null;
}

/**
 * Eine Saison außerhalb ihres Fensters, für `?saison=<id>` — zum Ansehen der
 * Designs und für die Bilder im Wiki. Unbekannte Kennungen ergeben `null`.
 */
export function vorschauSaison(id: string, jetzt: Date): Saison | null {
	if (!(SAISON_IDS as string[]).includes(id)) return null;
	return saison(id as SaisonId, jetzt.getFullYear());
}
