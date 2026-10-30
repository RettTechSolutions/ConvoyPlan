import { test, expect, type Page } from '@playwright/test';
import { lage, VERSTECKE } from '../src/lib/saison/ostereier';
import { orgAdmin, planung, tab } from './kontextmenue-attrappe';

/**
 * Ostereiersuche (Teil der Saison-Designs). Zusagen:
 *
 * 1. **Jeder Anker existiert.** Die Eier hängen an den `data-tour`-Ankern des
 *    Tutorials; benennt jemand einen um, läge ein Ei nirgends, und „alle
 *    gefunden" würde unerreichbar.
 * 2. **Gefunden bleibt gefunden**, je Jahr.
 * 3. **Das zehnte Ei feiert.** Das goldene im Org-Admin ist ein Bonus und
 *    zählt nicht mit.
 * 4. **Ohne eingeschaltete Saison keine Eier.**
 */

test.use({ timezoneId: 'Europe/Berlin' });

const OSTERN = '2027-03-27T12:00:00+01:00';
const SCHLUESSEL = 'ostern-2027';
const ei = (page: Page, versteck: string) => page.locator(`[data-versteck-ei="${versteck}"]`);

async function ostern(page: Page, gefunden: string[] = []) {
	await page.clock.setFixedTime(new Date(OSTERN));
	await page.addInitScript(([s, g]) => {
		localStorage.setItem(`convoyplan-saison:${s}`, 'an');
		if (g.length) localStorage.setItem(`convoyplan-ostereier:${s}`, JSON.stringify(g));
	}, [SCHLUESSEL, gefunden] as const);
}

test('die Lage eines Eis wechselt mit dem Jahr, bleibt aber innerhalb eines Jahres fest', () => {
	expect(lage('export', 'ostern-2027')).toEqual(lage('export', 'ostern-2027'));
	const jahre = ['ostern-2027', 'ostern-2028', 'ostern-2029', 'ostern-2030'].map((s) => JSON.stringify(lage('export', s)));
	expect(new Set(jahre).size).toBeGreaterThan(1);
});

test('jedes Versteck hat seinen Anker in der Planung', async ({ page }) => {
	await planung(page);
	const reiter = ['Plan', 'Route', 'Wegpunkte', 'Zeitplan', 'Fahrzeuge', 'Konto', 'Export'];
	const gesehen = new Set<string>();
	for (const name of reiter) {
		await tab(page, name).click();
		for (const v of VERSTECKE) {
			if (await page.locator(`[data-tour="${v}"]`).count()) gesehen.add(v);
		}
	}
	expect([...VERSTECKE].filter((v) => !gesehen.has(v))).toEqual([]);
});

test('ein gefundenes Ei verschwindet, zählt am Knopf und bleibt gefunden', async ({ page }) => {
	await ostern(page);
	await planung(page);
	await expect(ei(page, 'convoy-selector')).toBeVisible();
	await expect(page.getByRole('button', { name: /Saison-Design Ostern/ })).toContainText('0/10');

	await ei(page, 'convoy-selector').click();
	await expect(ei(page, 'convoy-selector')).toHaveCount(0);
	await expect(page.getByRole('status').filter({ hasText: '1 von 10' })).toBeVisible();
	await expect(page.getByRole('button', { name: /Saison-Design Ostern/ })).toContainText('1/10');

	await page.reload({ waitUntil: 'domcontentloaded' });
	await expect(ei(page, 'sidebar-footer')).toBeVisible();
	await expect(ei(page, 'convoy-selector')).toHaveCount(0);
});

test('Eier in anderen Reitern zeigen sich erst dort', async ({ page }) => {
	await ostern(page);
	await planung(page);
	await expect(ei(page, 'export')).toHaveCount(0);
	await tab(page, 'Export').click();
	await expect(ei(page, 'export')).toBeVisible();
});

test('das zehnte Ei feiert', async ({ page }) => {
	await ostern(page, VERSTECKE.filter((v) => v !== 'export'));
	await planung(page);
	await tab(page, 'Export').click();
	await ei(page, 'export').click();
	await expect(page.getByRole('status').filter({ hasText: 'Alle 10 Ostereier gefunden' })).toBeVisible();
	await expect(page.locator('canvas.saison-partikel[data-art="konfetti"]')).toBeAttached();
});

test('im Org-Admin liegt das goldene Ei, und es zählt nicht mit', async ({ page }) => {
	await ostern(page);
	await orgAdmin(page);
	await ei(page, 'gold').click();
	await expect(page.getByRole('status').filter({ hasText: 'goldene Ei' })).toBeVisible();
	const gefunden = await page.evaluate((s) => localStorage.getItem(`convoyplan-ostereier:${s}`), SCHLUESSEL);
	expect(JSON.parse(gefunden!)).toEqual(['gold']);
});

test('ohne eingeschaltete Saison liegen keine Eier', async ({ page }) => {
	await page.clock.setFixedTime(new Date(OSTERN));
	await planung(page);
	await expect(page.getByRole('button', { name: 'Saison-Design Ostern einschalten' })).toBeVisible();
	await expect(page.locator('.osterei')).toHaveCount(0);
});
