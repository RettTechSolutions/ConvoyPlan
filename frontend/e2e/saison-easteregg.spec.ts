import { test, expect, type Page } from '@playwright/test';
import { blockExternal, fahrzeug, mockTrack } from './fixtures';
import { orgAdmin, planung } from './kontextmenue-attrappe';

/**
 * Saison-Designs: ein Easter Egg. Die Zusagen, die man ihm nicht ansieht:
 *
 * 1. **Nur auf Klick.** Im Fenster einer Saison erscheint ein Knopf, sonst
 *    nichts. Außerhalb gibt es nicht einmal den Knopf.
 * 2. **Gemerkt je Saison und Jahr.** Wer Halloween 2026 eingeschaltet hat,
 *    sieht 2027 wieder nur den Knopf.
 * 3. **Nicht im Einsatz.** Fahrer-Link und Tracking bleiben neutral, auch
 *    wenn die Saison eingeschaltet ist.
 * 4. **Das Branding bleibt.** Die Primärfarbe der Organisation ändert sich nicht.
 * 5. **Reduzierte Bewegung heißt keine Partikel.**
 */

test.use({ timezoneId: 'Europe/Berlin' });

const knopf = (page: Page, name: RegExp | string = /Saison-Design/) => page.getByRole('button', { name });
const saison = (page: Page) => page.evaluate(() => document.documentElement.dataset.saison ?? null);

async function am(page: Page, datum: string) {
	await page.clock.setFixedTime(new Date(datum));
}

test('außerhalb einer Saison gibt es keinen Knopf', async ({ page }) => {
	await am(page, '2026-10-29T12:00:00+01:00');
	await planung(page);
	await expect(page.getByRole('button', { name: 'Fehler melden oder Funktion vorschlagen' })).toBeVisible();
	await expect(knopf(page)).toHaveCount(0);
	expect(await saison(page)).toBeNull();
});

test('an Halloween schaltet der Knopf das Design ein, und es bleibt nach dem Neuladen', async ({ page }) => {
	await am(page, '2026-10-31T18:00:00+01:00');
	await planung(page);
	const primaer = () => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--color-primary').trim());
	const vorher = await primaer();

	// Ohne Klick: Knopf ja, Design nein.
	await expect(knopf(page, 'Saison-Design Halloween einschalten')).toBeVisible();
	expect(await saison(page)).toBeNull();
	await expect(page.locator('.saison-band')).toHaveCount(0);

	await knopf(page, 'Saison-Design Halloween einschalten').click();
	expect(await saison(page)).toBe('halloween');
	await expect(knopf(page, 'Saison-Design Halloween ausschalten')).toHaveAttribute('aria-pressed', 'true');
	await expect(page.getByRole('status').filter({ hasText: 'Süßes oder Saures' })).toBeVisible();
	await expect(page.locator('.saison-band')).toBeVisible();
	await expect(page.locator('canvas.saison-partikel[data-art="fledermaeuse"]')).toBeAttached();
	expect(await primaer()).toBe(vorher);

	// Gemerkt — aber gegrüßt wird nur beim Einschalten.
	await page.reload({ waitUntil: 'domcontentloaded' });
	await expect(knopf(page, 'Saison-Design Halloween ausschalten')).toBeVisible();
	expect(await saison(page)).toBe('halloween');
	await expect(page.getByRole('status').filter({ hasText: 'Süßes oder Saures' })).toHaveCount(0);

	await knopf(page, 'Saison-Design Halloween ausschalten').click();
	expect(await saison(page)).toBeNull();
	await expect(page.locator('canvas.saison-partikel')).toHaveCount(0);
});

test('die Wahl gilt für ein Jahr: 2027 ist Halloween wieder aus', async ({ page }) => {
	await page.addInitScript(() => localStorage.setItem('convoyplan-saison:halloween-2026', 'an'));
	await am(page, '2027-10-31T12:00:00+01:00');
	await planung(page);
	await expect(knopf(page, 'Saison-Design Halloween einschalten')).toBeVisible();
	expect(await saison(page)).toBeNull();
});

test('mit reduzierter Bewegung gibt es Farben, aber keine Partikel', async ({ page }) => {
	await page.emulateMedia({ reducedMotion: 'reduce' });
	await page.addInitScript(() => localStorage.setItem('convoyplan-saison:advent-2026', 'an'));
	await am(page, '2026-12-12T12:00:00+01:00');
	await planung(page);
	await expect.poll(() => saison(page)).toBe('advent');
	await expect(page.locator('.saison-band')).toBeVisible();
	await expect(page.locator('canvas.saison-partikel')).toHaveCount(0);
});

test('der Fahrer-Link bleibt neutral, auch wenn die Saison eingeschaltet ist', async ({ page }) => {
	await page.addInitScript(() => localStorage.setItem('convoyplan-saison:halloween-2026', 'an'));
	await am(page, '2026-10-31T12:00:00+01:00');
	await blockExternal(page);
	await mockTrack(page, { scope: 'driver', fahrzeuge: [fahrzeug()] });
	await page.goto('/track/6dA4KrUG', { waitUntil: 'domcontentloaded' });
	await expect(page.getByRole('combobox', { name: 'Fahrzeug' })).toBeVisible();
	expect(await saison(page)).toBeNull();
	await expect(page.locator('.saison-band')).toHaveCount(0);
	await expect(page.locator('canvas.saison-partikel')).toHaveCount(0);
	await expect(knopf(page)).toHaveCount(0);
});

test('im Org-Admin steht der Knopf in der Kopfzeile', async ({ page }) => {
	await am(page, '2026-12-24T12:00:00+01:00');
	await orgAdmin(page);
	await knopf(page, 'Saison-Design Advent einschalten').click();
	expect(await saison(page)).toBe('advent');
	expect(await page.evaluate(() => localStorage.getItem('convoyplan-saison:advent-2026'))).toBe('an');
});

test('der Konami-Code schaltet ebenfalls um', async ({ page }) => {
	await am(page, '2026-04-01T09:00:00+02:00');
	await planung(page);
	await page.locator('body').click({ position: { x: 5, y: 5 } }).catch(() => {});
	for (const taste of ['ArrowUp', 'ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ArrowLeft', 'ArrowRight', 'b', 'a']) {
		await page.keyboard.press(taste);
	}
	expect(await saison(page)).toBe('april');
	await expect(page.getByRole('status')).toContainText('Sylt');
	await expect(page.getByRole('status')).toContainText('April, April', { timeout: 6000 });
});

test('?saison= zeigt ein Design außerhalb seines Fensters, zum Ansehen', async ({ page }) => {
	await am(page, '2026-10-29T12:00:00+01:00');
	await planung(page);
	await page.goto(page.url() + '?saison=ostern', { waitUntil: 'domcontentloaded' });
	await knopf(page, 'Saison-Design Ostern einschalten').click();
	expect(await saison(page)).toBe('ostern');
});
