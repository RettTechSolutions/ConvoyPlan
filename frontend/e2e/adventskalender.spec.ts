import { test, expect, type Page } from '@playwright/test';
import { bisTag, TUERCHEN, tuerchenHeute, versteck } from '../src/lib/saison/adventskalender';
import { planung, tab } from './kontextmenue-attrappe';

/**
 * Adventskalender (Teil der Saison-Designs). Zusagen:
 *
 * 1. **Das heutige Türchen muss man finden.** Es liegt an einem Anker in
 *    der Planung; den Kalender gibt es erst, wenn es gefunden ist.
 * 2. **Verpasste Tage lassen sich nachholen, künftige nicht.**
 * 3. **Geöffnet bleibt geöffnet**, und an der Stelle des Türchens liegt
 *    danach der Kalender zum Nachlesen.
 * 4. **Türchen 24 schickt den Schlittenkonvoi** — außer bei reduzierter Bewegung.
 */

test.use({ timezoneId: 'Europe/Berlin' });

const SCHLUESSEL = 'advent-2026';

/** In welchem Reiter der Planung ein Anker steht. */
const REITER: Record<string, string> = {
	'convoy-selector': 'Plan', 'plan-params': 'Plan', 'route-actions': 'Plan', 'sidebar-footer': 'Plan',
	waypoints: 'Wegpunkte', schedule: 'Zeitplan', vehicles: 'Fahrzeuge', konto: 'Konto',
	export: 'Export', tracking: 'Export',
};

async function advent(page: Page, datum: string, offen: number[] = []) {
	await page.clock.setFixedTime(new Date(datum));
	await page.addInitScript(([s, o]) => {
		localStorage.setItem(`convoyplan-saison:${s}`, 'an');
		if (o.length) localStorage.setItem(`convoyplan-advent:${s}`, JSON.stringify(o));
	}, [SCHLUESSEL, offen] as const);
	await planung(page);
}

async function zumVersteck(page: Page, tag: number) {
	await tab(page, REITER[versteck(tag, SCHLUESSEL)]).click();
}

const tuerchen = (page: Page) => page.locator('[data-advent="tuerchen"]');
const kalender = (page: Page) => page.locator('[data-advent="kalender"]');
const dialog = (page: Page) => page.getByRole('dialog');

test('Kalenderregeln: Türchen nur im Advent, nachholen bis heute, danach alle', () => {
	const am = (m: number, t: number) => new Date(2026, m - 1, t, 12);
	expect(tuerchenHeute(am(11, 30))).toBeNull();
	expect(tuerchenHeute(am(12, 1))).toBe(1);
	expect(tuerchenHeute(am(12, 24))).toBe(24);
	expect(tuerchenHeute(am(12, 25))).toBeNull();
	expect(bisTag(am(12, 12))).toBe(12);
	expect(bisTag(am(12, 26))).toBe(24);
	expect(TUERCHEN).toHaveLength(24);
	expect(REITER[versteck(1, SCHLUESSEL)]).toBeDefined();
});

test('das heutige Türchen finden, öffnen, und danach liegt dort der Kalender', async ({ page }) => {
	await advent(page, '2026-12-12T10:00:00+01:00');
	await zumVersteck(page, 12);
	await expect(tuerchen(page)).toBeVisible();
	await expect(page.getByRole('button', { name: /Saison-Design Advent/ })).toContainText('0/24');

	await tuerchen(page).click();
	await expect(dialog(page)).toContainText('Türchen 12');
	await expect(dialog(page)).toContainText(TUERCHEN[11].text);
	await page.keyboard.press('Escape');
	await expect(dialog(page)).toHaveCount(0);

	await page.reload({ waitUntil: 'domcontentloaded' });
	await zumVersteck(page, 12);
	await expect(tuerchen(page)).toHaveCount(0);
	await expect(kalender(page)).toBeVisible();
	await expect(page.getByRole('button', { name: /Saison-Design Advent/ })).toContainText('1/24');
});

test('verpasste Türchen lassen sich nachholen, das heutige und künftige nicht', async ({ page }) => {
	// Heute ist der 12., Türchen 12 schon gefunden: an seinem Platz liegt der Kalender.
	await advent(page, '2026-12-12T10:00:00+01:00', [12]);
	await zumVersteck(page, 12);
	await kalender(page).click();
	await expect(dialog(page)).toContainText('1 von 24');

	await expect(page.getByRole('button', { name: 'Türchen 13, noch geschlossen' })).toBeDisabled();
	await page.getByRole('button', { name: 'Türchen 3 nachholen' }).click();
	await expect(dialog(page)).toContainText(TUERCHEN[2].text);
	await expect(page.getByRole('button', { name: 'Türchen 3, geöffnet' })).toBeVisible();
});

test('vor dem Finden gibt es nur das Türchen, keinen Kalender zum Nachholen', async ({ page }) => {
	await advent(page, '2026-12-12T10:00:00+01:00', [11]);
	await zumVersteck(page, 12);
	await expect(tuerchen(page)).toBeVisible();
	await expect(kalender(page)).toHaveCount(0);
	await tuerchen(page).click();
	await expect(page.getByRole('button', { name: 'Türchen 12, geöffnet' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Türchen 11, geöffnet' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Türchen 10 nachholen' })).toBeEnabled();
});

test('Türchen 24 schickt den Schlittenkonvoi', async ({ page }) => {
	await advent(page, '2026-12-24T18:00:00+01:00');
	await zumVersteck(page, 24);
	await tuerchen(page).click();
	await expect(dialog(page)).toContainText('Frohe Weihnachten');
	await expect(page.locator('.advent-schlitten')).toBeAttached();
});

test('mit reduzierter Bewegung kein Schlitten, der Kalender geht trotzdem', async ({ page }) => {
	await page.emulateMedia({ reducedMotion: 'reduce' });
	await advent(page, '2026-12-24T18:00:00+01:00');
	await zumVersteck(page, 24);
	await tuerchen(page).click();
	await expect(dialog(page)).toContainText('Türchen 24');
	await expect(page.locator('.advent-schlitten')).toHaveCount(0);
});

test('nach Weihnachten ist alles nachzuholen', async ({ page }) => {
	await advent(page, '2026-12-26T12:00:00+01:00');
	await zumVersteck(page, 24);
	await kalender(page).click();
	await expect(page.getByRole('button', { name: 'Türchen 24 nachholen' })).toBeEnabled();
	await expect(page.getByRole('button', { name: /noch geschlossen/ })).toHaveCount(0);
});
