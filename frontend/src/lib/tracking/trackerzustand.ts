/**
 * Akku und Empfang eines Trackers, wie Org-Admin und Konvoi-Ansicht sie zeigen.
 *
 * Ob der Akku warnt, entscheidet das Backend (`akku_niedrig`,
 * `services/ortungsgeraet.py`) — hier steht nur, wie es aussieht. Die Balken
 * rechnen aus `signal_dbm` (RSRP des LTE-M-/NB-IoT-Moduls) und dem letzten
 * Kontakt; eine Meldung, die älter ist als `EMPFANG_VERALTET_MS`, sagt über den
 * Empfang von jetzt nichts mehr.
 */

/** Ab hier gelten die Balken als veraltet (grau). Ein Tracker im laufenden
 *  Konvoi sendet alle 30 s; steht das Fahrzeug, schläft er nach fünf Minuten. */
export const EMPFANG_VERALTET_MS = 10 * 60 * 1000;

/** RSRP-Schwellen für 4/3/2/1 Balken, darunter keiner. */
const SCHWELLEN_DBM = [-90, -100, -110, -120] as const;

export function balken(dbm: number | null): number {
	if (dbm === null) return 0;
	const i = SCHWELLEN_DBM.findIndex((s) => dbm >= s);
	return i === -1 ? 0 : 4 - i;
}

export const EMPFANG_TEXT = ['kein Empfang', 'schwacher Empfang', 'mäßiger Empfang', 'guter Empfang', 'sehr guter Empfang'];

export function veraltet(zuletzt: string | null, jetzt: number): boolean {
	return !zuletzt || jetzt - new Date(zuletzt).getTime() > EMPFANG_VERALTET_MS;
}

/** „vor 3 min", „vor 5 Std.", „vor 2 Tagen" — für Kontakt und „auf Akku seit". */
export function dauer(iso: string, jetzt: number): string {
	const min = Math.max(0, Math.round((jetzt - new Date(iso).getTime()) / 60000));
	if (min < 1) return 'gerade eben';
	if (min < 60) return `${min} min`;
	const std = Math.round(min / 60);
	if (std < 48) return `${std} Std.`;
	return `${Math.round(std / 24)} Tagen`;
}

export interface TrackerAnzeige {
	akku_prozent: number | null;
	extern: boolean | null;
	auf_akku_seit: string | null;
	akku_niedrig: boolean;
	signal_dbm: number | null;
	zuletzt_gesehen: string | null;
}

export function akkuTitel(t: TrackerAnzeige, jetzt: number): string {
	if (t.akku_prozent === null) return 'Akku: keine Angabe';
	const teile = [`Akku ${t.akku_prozent} %`];
	if (t.extern) teile.push('am Bordnetz, lädt');
	else if (t.auf_akku_seit) teile.push(`auf Akku seit ${dauer(t.auf_akku_seit, jetzt)}`);
	if (t.akku_niedrig) teile.push('schwach');
	return teile.join(' · ');
}

export function empfangTitel(t: TrackerAnzeige, jetzt: number): string {
	if (!t.zuletzt_gesehen) return 'Noch nie gemeldet';
	const kontakt = `letzter Kontakt vor ${dauer(t.zuletzt_gesehen, jetzt)}`.replace('vor gerade eben', 'gerade eben');
	if (veraltet(t.zuletzt_gesehen, jetzt)) return `Keine aktuelle Verbindung · ${kontakt}`;
	const b = balken(t.signal_dbm);
	const dbm = t.signal_dbm === null ? '' : ` (${t.signal_dbm} dBm)`;
	return `${EMPFANG_TEXT[b][0].toUpperCase()}${EMPFANG_TEXT[b].slice(1)}${dbm} · ${kontakt}`;
}
