import { test, expect, type Page } from '@playwright/test';
import { blockExternal, fahrzeug, mockTrack, position } from './fixtures';

// Fahrer-Link am Telefon. Zusagen, die man einem Bildschirmfoto nur halb ansieht:
//
// - **Die Kartenknöpfe liegen nicht auf der OSM-Nennung.** Die ist am Telefon
//   zweizeilig, und „Konvoi" stand vorher darauf.
// - **Die Schublade beginnt mit dem eigenen Fahrzeug**, nicht mit einem Logo in
//   voller Breite.
// - **Die Stärke-Felder tragen die Farben der Leiste**, nicht Browserweiß.

const TELEFON = { width: 390, height: 844 };
test.use({ viewport: TELEFON, hasTouch: true });

async function oeffnen(page: Page) {
	await blockExternal(page);
	await mockTrack(page, {
		scope: 'driver',
		fahrzeuge: [
			fahrzeug({ id: 'v1', name: 'HLF 20', callsign: 'Florian 1/46', vehicle_status: 'en_route' }),
			fahrzeug({ id: 'v2', name: 'MTW', callsign: 'Florian 1/19', position: 2, vehicle_status: 'planned' }),
		],
		positionen: [position('v1')],
	});
	await page.goto('/track/6dA4KrUG', { waitUntil: 'domcontentloaded' });
	await expect(page.locator('.map-ctrl-btn').first()).toBeVisible();
}

test('die Kartenknöpfe enden über der OSM-Nennung', async ({ page }) => {
	await oeffnen(page);
	const nennung = (await page.locator('.maplibregl-ctrl-attrib').boundingBox())!;
	const knoepfe = page.locator('.map-ctrl-btn');
	for (let i = 0; i < (await knoepfe.count()); i++) {
		const b = (await knoepfe.nth(i).boundingBox())!;
		expect(b.y + b.height).toBeLessThanOrEqual(nennung.y);
	}
});

test('die Schublade beginnt mit dem eigenen Fahrzeug, und die Stärke-Felder sind nicht weiß', async ({ page }) => {
	await oeffnen(page);
	await page.getByRole('button', { name: 'Menü', exact: true }).click();
	const wahl = page.locator('.sidebar select').first();
	// Mit dem Logo in voller Breite stand die Fahrzeugwahl bei 300 px, kompakt bei 248 px.
	expect((await wahl.boundingBox())!.y).toBeLessThan(275);

	await wahl.selectOption('v1');
	const feld = page.getByTestId('staerke-form-fahrer').locator('input').first();
	await expect(feld).toBeVisible();
	expect(await feld.evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe('rgb(255, 255, 255)');
});
