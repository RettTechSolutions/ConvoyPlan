import { test, expect, type Page } from '@playwright/test';
import { blockExternal, konvoiFahrzeug, mockOrgPortal, position } from './fixtures';

// Tracking-Ansicht am Telefon. Zusagen, die man einem Bildschirmfoto nur halb
// ansieht:
//
// - **Die Kartenknöpfe decken die Karte nicht zu.** Hochkant sind sie runde
//   Symbole statt Pillen mit Text — bis zu sechs Pillen untereinander lagen auf
//   einem Drittel der Karte und auf der OSM-Nennung. Ihr Name bleibt für
//   Screenreader und Tests derselbe.
// - **Quer bleibt der Text**, dort ist Platz in der Breite.
// - **Die Schublade beginnt mit dem, was im Einsatz zählt**: Der Kopf mit Logo
//   ist klein, „Meine Position" steht weiter oben.

const SLUG = 'thw-musterstadt';
const CONVOY = '11111111-1111-1111-1111-111111111111';
const HOCHKANT = { width: 390, height: 844 };
const QUER = { width: 844, height: 390 };

async function oeffnen(page: Page) {
	await blockExternal(page);
	await mockOrgPortal(page, {
		slug: SLUG,
		convoyId: CONVOY,
		fahrzeuge: [konvoiFahrzeug({ vehicle_status: 'en_route', vehicle: { id: 'v1', name: 'HLF 20', callsign: 'Florian 1/46' } })],
		positionen: [position('v1')],
	});
	await page.goto(`/o/${SLUG}/tracking/${CONVOY}`, { waitUntil: 'domcontentloaded' });
	// Mit eigenem Fahrzeug erscheinen alle Knöpfe, auch „Fahrtrichtung" und „Mein Fahrzeug".
	await page.getByLabel('Meine Position').selectOption('v1');
	await expect(page.getByRole('button', { name: 'Mein Fahrzeug' })).toBeVisible();
}

test.describe('hochkant', () => {
	test.use({ viewport: HOCHKANT, hasTouch: true });

	test('Kartenknöpfe sind runde Symbole über der OSM-Nennung, mit ihrem Namen', async ({ page }) => {
		await oeffnen(page);
		const knoepfe = page.locator('.map-ctrl-btn');
		const anzahl = await knoepfe.count();
		expect(anzahl).toBeGreaterThanOrEqual(4);
		for (const name of ['Norden', 'Konvoi', 'Fahrtrichtung', 'Mein Fahrzeug']) {
			await expect(page.getByRole('button', { name, exact: true })).toBeVisible();
		}

		const nennung = (await page.locator('.maplibregl-ctrl-attrib').boundingBox())!;
		for (let i = 0; i < anzahl; i++) {
			const b = (await knoepfe.nth(i).boundingBox())!;
			expect(b.width, 'Knopf so schmal wie ein Symbol').toBeLessThanOrEqual(48);
			expect(b.y + b.height, 'Knopf endet über der OSM-Nennung').toBeLessThanOrEqual(nennung.y);
		}
		await expect(page.locator('.map-ctrl-btn .ctrl-text').first()).toBeHidden();
	});

	test('die Schublade zeigt „Meine Position" weit oben', async ({ page }) => {
		await oeffnen(page);
		await page.getByRole('button', { name: 'Menü', exact: true }).click();
		// Mit dem Logo in voller Breite stand das Feld bei 391 px, kompakt bei 339 px.
		const feld = (await page.getByLabel('Meine Position').boundingBox())!;
		expect(feld.y).toBeLessThan(365);
	});
});

test.describe('quer', () => {
	test.use({ viewport: QUER, hasTouch: true });

	test('die Kartenknöpfe tragen ihren Text', async ({ page }) => {
		await oeffnen(page);
		await expect(page.locator('.map-ctrl-btn .ctrl-text', { hasText: 'Norden' })).toBeVisible();
	});
});
