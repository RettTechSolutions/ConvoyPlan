/**
 * Die Handbücher als PDF, ausgeliefert aus `static/handbuecher/`.
 *
 * Der Katalog entsteht mit den PDFs (`docs/handbuecher/build.py`) und steht
 * deshalb als JSON daneben: Seitenzahl und Größe stimmen nur, wenn sie aus
 * derselben Erzeugung kommen. Von Hand gepflegt wird hier nichts.
 */
import katalog from './katalog.json';

export interface Handbuch {
	datei: string;
	titel: string;
	beschreibung: string;
	fuer: string;
	seiten: number;
	bytes: number;
	stand: string;
}

export const HANDBUECHER: Handbuch[] = katalog;

/** Adresse des PDFs auf dieser Instanz. */
export const handbuchUrl = (h: Handbuch) => `/handbuecher/${h.datei}`;

/** „7,5 MB" — gerundet, wie man eine Downloadgröße liest. */
export function groesse(bytes: number): string {
	const mb = bytes / 1_000_000;
	return mb >= 1
		? `${mb.toLocaleString('de-DE', { maximumFractionDigits: 1 })} MB`
		: `${Math.max(1, Math.round(bytes / 1000)).toLocaleString('de-DE')} KB`;
}

/** „31.10.2026" aus dem ISO-Datum der Erzeugung. */
export const stand = (h: Handbuch) => h.stand.split('-').reverse().join('.');
