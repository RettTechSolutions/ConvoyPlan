import { test, expect, type Page } from '@playwright/test';
import { ausgang, SAURES, SUESSES, ZIEL } from '../src/lib/saison/geisterjagd';
import { planung } from './kontextmenue-attrappe';

/**
 * Geisterjagd zu Halloween (Teil der Saison-Designs). Zusagen:
 *
 * 1. **Geister erscheinen nur, wo man sie sieht**, und lassen sich fangen.
 * 2. **Gefangen bleibt gefangen**, je Jahr, und der Stand steht am Knopf.
 * 3. **Der 13. macht zum Geisterjäger.**
 * 4. **Saures ist harmlos** und bei reduzierter Bewegung ganz aus.
 */

test.use({ timezoneId: 'Europe/Berlin' });

const SCHLUESSEL = 'halloween-2026';
const geist = (page: Page) => page.locator('[data-geist]');
const knopf = (page: Page) => page.getByRole('button', { name: /Saison-Design Halloween/ });

async function halloween(page: Page, gefangen = 0, zufall?: number) {
	await page.clock.setFixedTime(new Date('2026-10-31T20:00:00+01:00'));
	await page.addInitScript(([s, n, z]) => {
		localStorage.setItem(`convoyplan-saison:${s}`, 'an');
		if (n) localStorage.setItem(`convoyplan-geister:${s}`, String(n));
		if (z !== null) Math.random = () => z;
	}, [SCHLUESSEL, gefangen, zufall ?? null] as const);
	await planung(page);
}

test('Süßes und Saures kommen beide vor', () => {
	expect(SUESSES).toContain(ausgang(0));
	expect(SUESSES).toContain(ausgang(0.49));
	expect(SAURES).toContain(ausgang(0.5));
	expect(SAURES).toContain(ausgang(0.99));
	expect(SAURES.every((a) => a.saures)).toBe(true);
});

test('ein Geist erscheint, lässt sich fangen und zählt am Knopf', async ({ page }) => {
	await halloween(page, 0, 0.1);
	await expect(knopf(page)).toContainText(`0/${ZIEL}`);
	await expect(geist(page)).toBeVisible({ timeout: 6000 });
	await geist(page).click();
	await expect(geist(page)).toHaveCount(0);
	await expect(page.getByRole('status').filter({ hasText: 'Süßes!' })).toContainText('👻 1');
	await expect(knopf(page)).toContainText(`1/${ZIEL}`);

	await page.reload({ waitUntil: 'domcontentloaded' });
	await expect(knopf(page)).toContainText(`1/${ZIEL}`);
});

test('ein Geist verschwindet wieder, wenn niemand ihn fängt', async ({ page }) => {
	await halloween(page);
	await expect(geist(page)).toBeVisible({ timeout: 6000 });
	await expect(geist(page)).toHaveCount(0, { timeout: 7000 });
});

test('Saures: die Spinne lässt sich fallen', async ({ page }) => {
	await halloween(page, 0, 0.75);
	await geist(page).click({ timeout: 6000 });
	await expect(page.getByRole('status').filter({ hasText: 'Saures!' })).toBeVisible();
	await expect.poll(() => page.evaluate(() => document.documentElement.dataset.saures ?? null)).toBe('spinne');
	await expect.poll(() => page.evaluate(() => document.documentElement.dataset.saures ?? null), { timeout: 5000 }).toBeNull();
});

test('der 13. Geist macht zum Geisterjäger', async ({ page }) => {
	await halloween(page, ZIEL - 1);
	await geist(page).click({ timeout: 6000 });
	await expect(page.getByRole('status')).toContainText('Geisterjäger');
	await expect(page.locator('.geist-schwarm')).toBeAttached();
	await expect(knopf(page)).toContainText(`🏆`);
});

test('mit reduzierter Bewegung gibt es Geister, aber kein Saures', async ({ page }) => {
	await page.emulateMedia({ reducedMotion: 'reduce' });
	await halloween(page, 0, 0.6);
	await geist(page).click({ timeout: 6000 });
	await expect(page.getByRole('status').filter({ hasText: 'Saures!' })).toBeVisible();
	expect(await page.evaluate(() => document.documentElement.dataset.saures ?? null)).toBeNull();
	await expect(page.locator('.geist-schwarm')).toHaveCount(0);
});

test('ohne eingeschaltete Saison spukt nichts', async ({ page }) => {
	await page.clock.setFixedTime(new Date('2026-10-31T20:00:00+01:00'));
	await planung(page);
	await page.waitForTimeout(3500);
	await expect(geist(page)).toHaveCount(0);
});
