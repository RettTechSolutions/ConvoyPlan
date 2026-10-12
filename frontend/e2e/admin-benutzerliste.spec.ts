import { test, expect } from '@playwright/test';
import { benutzerListe, umschalten, STANDARD_SORTIERUNG, type BenutzerZeile } from '../src/lib/admin/benutzerliste';

// Benutzerliste im Admin-Portal. Das Backend liefert nach Anlegedatum, der
// Betreiber sucht nach Namen und Organisation. Die Zusagen:
//  - ohne Klick steht die Liste nach Nachname, dann Vorname;
//  - Konten ohne Namen (bzw. ohne Organisation) stehen in beiden Richtungen
//    unten, statt beim Umdrehen nach oben zu springen;
//  - Demo-Sitzungen bleiben unter den echten Konten, egal wonach sortiert
//    oder gefiltert wird;
//  - die Suche findet über Name, E-Mail und Organisation, mehrere Wörter
//    müssen alle passen; der Org-Filter nimmt nur Mitglieder.
// Reine Regeln ohne Oberfläche — die Seite sitzt hinter der Superadmin-Anmeldung.

const org = (id: string, name: string, role = 'planer') => ({ id, name, role });
const JUH_P = org('p', 'Johanniter Peißenberg');
const JUH_W = org('w', 'Johanniter Weihnachtstrucker');
const OWLS = org('o', 'MrOWLS Test Orga');

function benutzer(
	email: string,
	first_name: string | null,
	last_name: string | null,
	orgs: BenutzerZeile['orgs'],
	extra: Partial<BenutzerZeile> = {},
): BenutzerZeile {
	return { email, first_name, last_name, orgs, is_active: true, is_superadmin: false, is_demo: false, mfa_enabled: false, ...extra };
}

const ALLE: BenutzerZeile[] = [
	benutzer('christoph@convoyplan.de', 'Christoph', 'Zeitler', [OWLS, JUH_P], { is_superadmin: true, mfa_enabled: true }),
	benutzer('demo-1@demo.local', null, null, [org('d', 'Demo 23FD30')], { is_demo: true }),
	benutzer('david@example.org', 'David', 'Schäffler', [OWLS]),
	benutzer('anna@example.org', 'Anna-Maria', 'Lutz', [JUH_P]),
	benutzer('ohne-name@example.org', null, null, [JUH_W]),
	benutzer('christian.h@example.org', 'Christian', 'Hoffer', [JUH_W], { is_active: false }),
	benutzer('christian.s@example.org', 'Christian', 'Stögbauer', [JUH_W]),
	benutzer('app@example.org', 'App', 'Test', []),
];

const mails = (l: BenutzerZeile[]) => l.map((u) => u.email);

test('ohne Klick nach Nachname, ohne Namen und Demo am Ende', () => {
	expect(mails(benutzerListe(ALLE))).toEqual([
		'christian.h@example.org', // Hoffer
		'anna@example.org', // Lutz
		'david@example.org', // Schäffler
		'christian.s@example.org', // Stögbauer
		'app@example.org', // Test
		'christoph@convoyplan.de', // Zeitler
		'ohne-name@example.org',
		'demo-1@demo.local',
	]);
});

test('umgedreht bleiben Namenlose und Demo unten', () => {
	const absteigend = umschalten(STANDARD_SORTIERUNG, 'name');
	expect(absteigend).toEqual({ spalte: 'name', absteigend: true });
	const l = mails(benutzerListe(ALLE, absteigend));
	expect(l[0]).toBe('christoph@convoyplan.de');
	expect(l.slice(-2)).toEqual(['ohne-name@example.org', 'demo-1@demo.local']);
});

test('nach Organisation: alphabetisch nach der ersten, ohne Organisation unten', () => {
	const l = mails(benutzerListe(ALLE, { spalte: 'orgs', absteigend: false }));
	// Johanniter Peißenberg (Lutz, Zeitler), dann Weihnachtstrucker (Hoffer, Stögbauer, namenlos), dann MrOWLS.
	expect(l).toEqual([
		'anna@example.org',
		'christoph@convoyplan.de',
		'christian.h@example.org',
		'christian.s@example.org',
		'ohne-name@example.org',
		'david@example.org',
		'app@example.org',
		'demo-1@demo.local',
	]);
	const ab = mails(benutzerListe(ALLE, { spalte: 'orgs', absteigend: true }));
	expect(ab.slice(-2)).toEqual(['app@example.org', 'demo-1@demo.local']);
});

test('Ja/Nein-Spalten: aufsteigend steht „Ja" oben', () => {
	expect(benutzerListe(ALLE, { spalte: 'superadmin', absteigend: false })[0].email).toBe('christoph@convoyplan.de');
	expect(benutzerListe(ALLE, { spalte: 'aktiv', absteigend: true })[0].email).toBe('christian.h@example.org');
});

test('Suche über Name, E-Mail und Organisation, alle Wörter müssen passen', () => {
	expect(mails(benutzerListe(ALLE, STANDARD_SORTIERUNG, 'weihnacht'))).toEqual([
		'christian.h@example.org',
		'christian.s@example.org',
		'ohne-name@example.org',
	]);
	expect(mails(benutzerListe(ALLE, STANDARD_SORTIERUNG, 'christian stög'))).toEqual(['christian.s@example.org']);
	expect(mails(benutzerListe(ALLE, STANDARD_SORTIERUNG, 'CONVOYPLAN.DE'))).toEqual(['christoph@convoyplan.de']);
});

test('Org-Filter nimmt nur Mitglieder, Demo fällt dabei raus', () => {
	expect(mails(benutzerListe(ALLE, STANDARD_SORTIERUNG, '', 'p'))).toEqual(['anna@example.org', 'christoph@convoyplan.de']);
});
