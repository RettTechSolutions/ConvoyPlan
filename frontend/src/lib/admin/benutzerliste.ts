/**
 * Sortieren und Filtern der Benutzerliste im Admin-Portal.
 *
 * Ohne Svelte und ohne `$lib`-Importe, damit `e2e/admin-benutzerliste.spec.ts`
 * die Regeln direkt prüfen kann. Das Backend liefert nach Anlegedatum; das
 * sagt dem Betreiber nichts, gesucht wird nach Namen und Organisation.
 */

export interface BenutzerZeile {
	email: string;
	first_name: string | null;
	last_name: string | null;
	is_active: boolean;
	is_superadmin: boolean;
	is_demo: boolean;
	mfa_enabled: boolean;
	orgs: { id: string; name: string; role: string }[];
}

export type BenutzerSpalte = 'name' | 'email' | 'orgs' | 'aktiv' | 'superadmin' | 'mfa';

export interface BenutzerSortierung {
	spalte: BenutzerSpalte;
	absteigend: boolean;
}

export const STANDARD_SORTIERUNG: BenutzerSortierung = { spalte: 'name', absteigend: false };

const vergleich = new Intl.Collator('de', { sensitivity: 'base', numeric: true });

const leer = (s: string | null | undefined) => !s || !s.trim();

/** Ohne Namen ans Ende, unabhängig von der Richtung — „—" ist kein Name. */
function nachName(a: BenutzerZeile, b: BenutzerZeile): number {
	const aLeer = leer(a.last_name) && leer(a.first_name);
	const bLeer = leer(b.last_name) && leer(b.first_name);
	if (aLeer !== bLeer) return aLeer ? 1 : -1;
	return (
		vergleich.compare(a.last_name ?? '', b.last_name ?? '') ||
		vergleich.compare(a.first_name ?? '', b.first_name ?? '')
	);
}

/** Organisationen einer Zeile alphabetisch — sonst stünden sie in Beitrittsreihenfolge. */
export function orgsSortiert<T extends { name: string }>(orgs: T[]): T[] {
	return [...orgs].sort((a, b) => vergleich.compare(a.name, b.name));
}

function erstOrg(u: BenutzerZeile): string | null {
	return orgsSortiert(u.orgs)[0]?.name ?? null;
}

function nachSpalte(spalte: BenutzerSpalte, a: BenutzerZeile, b: BenutzerZeile): number {
	switch (spalte) {
		case 'name':
			return nachName(a, b);
		case 'email':
			return vergleich.compare(a.email, b.email);
		case 'orgs': {
			const oa = erstOrg(a);
			const ob = erstOrg(b);
			if ((oa === null) !== (ob === null)) return oa === null ? 1 : -1;
			return vergleich.compare(oa ?? '', ob ?? '');
		}
		// Bei Ja/Nein-Spalten steht „Ja" bei aufsteigender Sortierung oben:
		// wer auf „Superadmin" klickt, will die Superadmins sehen.
		case 'aktiv':
			return Number(b.is_active) - Number(a.is_active);
		case 'superadmin':
			return Number(b.is_superadmin) - Number(a.is_superadmin);
		case 'mfa':
			return Number(b.mfa_enabled) - Number(a.mfa_enabled);
	}
}

/** Ob eine Zeile ohne Wert in der Spalte ist — die bleibt in beiden Richtungen unten. */
function ohneWert(spalte: BenutzerSpalte, u: BenutzerZeile): boolean {
	if (spalte === 'name') return leer(u.last_name) && leer(u.first_name);
	if (spalte === 'orgs') return u.orgs.length === 0;
	return false;
}

/**
 * Filtern und sortieren. Demo-Sitzungen bleiben eine eigene Gruppe am Ende,
 * egal wonach sortiert wird — sie sind Durchlauf, keine Konten. Gleichstand
 * entscheidet der Name, danach die E-Mail, damit die Reihenfolge nicht springt.
 */
export function benutzerListe<T extends BenutzerZeile>(
	alle: T[],
	sortierung: BenutzerSortierung = STANDARD_SORTIERUNG,
	suche = '',
	orgId = '',
): T[] {
	const begriff = suche.trim().toLocaleLowerCase('de');
	const treffer = alle.filter((u) => {
		if (orgId && !u.orgs.some((o) => o.id === orgId)) return false;
		if (!begriff) return true;
		const text = [u.first_name, u.last_name, u.email, ...u.orgs.map((o) => o.name)]
			.filter(Boolean)
			.join(' ')
			.toLocaleLowerCase('de');
		return begriff.split(/\s+/).every((teil) => text.includes(teil));
	});

	const { spalte, absteigend } = sortierung;
	const richtung = absteigend ? -1 : 1;
	const sortiert = [...treffer].sort((a, b) => {
		const leerA = ohneWert(spalte, a);
		const leerB = ohneWert(spalte, b);
		if (leerA !== leerB) return leerA ? 1 : -1;
		return (
			richtung * nachSpalte(spalte, a, b) ||
			nachName(a, b) ||
			vergleich.compare(a.email, b.email)
		);
	});

	return [...sortiert.filter((u) => !u.is_demo), ...sortiert.filter((u) => u.is_demo)];
}

/** Klick auf eine Spaltenüberschrift: gleiche Spalte dreht, neue beginnt aufsteigend. */
export function umschalten(aktuell: BenutzerSortierung, spalte: BenutzerSpalte): BenutzerSortierung {
	return aktuell.spalte === spalte
		? { spalte, absteigend: !aktuell.absteigend }
		: { spalte, absteigend: false };
}
