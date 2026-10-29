import { test, expect } from '@playwright/test';
import { aktuelleSaison, ostersonntag, vorschauSaison, wiesn } from '../src/lib/saison/kalender';

/**
 * Wann welche Saison ist. Reine Rechnung ohne Browser — die Grenzen sieht
 * man der Oberfläche nur an genau einem Tag im Jahr an.
 */

const am = (j: number, m: number, t: number, h = 12, min = 0) => new Date(j, m - 1, t, h, min);
const id = (d: Date) => aktuelleSaison(d)?.id ?? null;
const tag = (d: Date) => `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;

test('Ostersonntag nach dem gregorianischen Kalender', () => {
	expect(tag(ostersonntag(2024))).toBe('2024-3-31');
	expect(tag(ostersonntag(2025))).toBe('2025-4-20');
	expect(tag(ostersonntag(2026))).toBe('2026-4-5');
	expect(tag(ostersonntag(2027))).toBe('2027-3-28');
	// Frühester und spätester möglicher Termin.
	expect(tag(ostersonntag(2285))).toBe('2285-3-22');
	expect(tag(ostersonntag(2038))).toBe('2038-4-25');
});

test('Wiesn: Samstag nach dem 15. September bis erster Oktobersonntag, mindestens bis zum 3.', () => {
	const w = (j: number) => { const { von, bis } = wiesn(j); return `${tag(von)} – ${tag(bis)}`; };
	expect(w(2025)).toBe('2025-9-20 – 2025-10-5');
	expect(w(2026)).toBe('2026-9-19 – 2026-10-4');
	expect(w(2023)).toBe('2023-9-16 – 2023-10-3');
});

test('Halloween gilt vom 30.10. bis zum 1.11., jeweils den ganzen Tag', () => {
	expect(id(am(2026, 10, 29, 23, 59))).toBeNull();
	expect(id(am(2026, 10, 30, 0, 0))).toBe('halloween');
	expect(id(am(2026, 11, 1, 23, 59))).toBe('halloween');
	expect(id(am(2026, 11, 2, 0, 0))).toBeNull();
	expect(aktuelleSaison(am(2026, 10, 31))?.schluessel).toBe('halloween-2026');
});

test('Advent bis zum 26.12., danach Winter bis Dreikönig — über den Jahreswechsel unter einem Schlüssel', () => {
	expect(id(am(2026, 11, 30))).toBeNull();
	expect(id(am(2026, 12, 1, 0, 0))).toBe('advent');
	expect(id(am(2026, 12, 26, 23, 59))).toBe('advent');
	expect(aktuelleSaison(am(2026, 12, 27))?.schluessel).toBe('winter-2026');
	expect(aktuelleSaison(am(2027, 1, 6, 23, 59))?.schluessel).toBe('winter-2026');
	expect(id(am(2027, 1, 7, 0, 0))).toBeNull();
});

test('am 5. Dezember grüßt der Advent zum Tag des Ehrenamts', () => {
	expect(aktuelleSaison(am(2026, 12, 5))?.gruss.join(' ')).toContain('Ehrenamt');
	expect(aktuelleSaison(am(2026, 12, 6))?.gruss.join(' ')).not.toContain('Ehrenamt');
});

test('Feuerwerk nur in der Silvesternacht, von 23 bis 1 Uhr', () => {
	const p = (d: Date) => aktuelleSaison(d)?.partikel;
	expect(p(am(2026, 12, 31, 22, 59))).toBe('schnee');
	expect(p(am(2026, 12, 31, 23, 0))).toBe('feuerwerk');
	expect(p(am(2027, 1, 1, 0, 59))).toBe('feuerwerk');
	expect(p(am(2027, 1, 1, 1, 0))).toBe('schnee');
});

test('Fasching von Weiberfastnacht bis Faschingsdienstag, Ostern von Gründonnerstag bis Ostermontag', () => {
	// 2026: Ostern am 5.4., Weiberfastnacht am 12.2., Aschermittwoch am 18.2.
	expect(id(am(2026, 2, 12))).toBe('fasching');
	expect(id(am(2026, 2, 17))).toBe('fasching');
	expect(id(am(2026, 2, 18))).toBeNull();
	expect(id(am(2026, 4, 1))).toBe('april');
	expect(id(am(2026, 4, 2))).toBe('ostern');
	expect(id(am(2026, 4, 6))).toBe('ostern');
	expect(id(am(2026, 4, 7))).toBeNull();
});

test('eintägige Anlässe gehen vor: 112 im Fasching, der 1. April an Ostern', () => {
	// 2029: Ostern am 1.4., Fasching vom 8. bis 13.2.
	expect(id(am(2029, 2, 10))).toBe('fasching');
	expect(id(am(2029, 2, 11))).toBe('notruf');
	expect(id(am(2029, 4, 1))).toBe('april');
	expect(id(am(2029, 4, 2))).toBe('ostern');
});

test('Wiesn 2026 vom 19.9. bis 4.10.', () => {
	expect(id(am(2026, 9, 18))).toBeNull();
	expect(id(am(2026, 9, 19))).toBe('wiesn');
	expect(id(am(2026, 10, 4))).toBe('wiesn');
	expect(id(am(2026, 10, 5))).toBeNull();
});

test('die Vorschau kennt nur die Saisons, die es gibt', () => {
	expect(vorschauSaison('ostern', am(2026, 10, 29))?.id).toBe('ostern');
	expect(vorschauSaison('karneval', am(2026, 10, 29))).toBeNull();
});
