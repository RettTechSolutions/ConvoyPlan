import { test, expect, type Page } from '@playwright/test';
import { blockExternal, konvoiFahrzeug, mockOrgPortal, position } from './fixtures';

// Tracking-Ansicht am Telefon. Zusagen, die man einem Bildschirmfoto nur halb
// ansieht:
//
// - **Die Kartenknöpfe decken die Karte nicht zu.** Hochkant steht nur „⋯";
//   bis zu sechs Pillen untereinander lagen auf einem Drittel der Karte und auf
//   der OSM-Nennung. Aufgeklappt sind es Pillen mit Text, nach einer Wahl oder
//   einem Tipp auf die Karte klappen sie wieder zu.
// - **Folgt die Karte, sieht man es auch zugeklappt** (grüner Punkt an „⋯").
// - **Quer bleibt die Zeile mit Text**, immer sichtbar, ohne „⋯".
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
	// Mit eigenem Fahrzeug gibt es alle Knöpfe, auch „Fahrtrichtung" und „Mein Fahrzeug".
	await page.getByLabel('Meine Position').selectOption('v1');
	// Über den Selektor: Zugeklappt ist der Knopf `display: none`, `getByRole` sähe ihn nicht.
	await expect(page.locator('.map-ctrl-btn[aria-label="Mein Fahrzeug"]')).toBeAttached();
}

const mehr = (page: Page) => page.locator('.ctrl-more');

test.describe('hochkant', () => {
	test.use({ viewport: HOCHKANT, hasTouch: true });

	test('zugeklappt steht nur „⋯" über der OSM-Nennung', async ({ page }) => {
		await oeffnen(page);
		await expect(mehr(page)).toBeVisible();
		await expect(mehr(page)).toHaveAttribute('aria-expanded', 'false');
		await expect(page.locator('.map-ctrl-btn:visible')).toHaveCount(0);

		const nennung = (await page.locator('.maplibregl-ctrl-attrib').boundingBox())!;
		const b = (await mehr(page).boundingBox())!;
		expect(b.y + b.height, '„⋯" endet über der OSM-Nennung').toBeLessThanOrEqual(nennung.y);
	});

	test('„⋯" klappt Pillen mit Text auf, eine Wahl klappt sie wieder zu', async ({ page }) => {
		await oeffnen(page);
		await mehr(page).tap();
		await expect(mehr(page)).toHaveAttribute('aria-expanded', 'true');
		for (const name of ['Norden', 'Konvoi', 'Fahrtrichtung', 'Mein Fahrzeug']) {
			await expect(page.getByRole('button', { name, exact: true })).toBeVisible();
		}
		await expect(page.locator('.map-ctrl-btn .ctrl-text', { hasText: 'Norden' })).toBeVisible();

		await page.getByRole('button', { name: 'Norden', exact: true }).tap();
		await expect(mehr(page)).toHaveAttribute('aria-expanded', 'false');
		await expect(page.getByRole('button', { name: 'Norden', exact: true })).toBeHidden();
	});

	test('ein Tipp auf die Karte klappt die Pillen zu', async ({ page }) => {
		await oeffnen(page);
		await mehr(page).tap();
		await expect(page.getByRole('button', { name: 'Norden', exact: true })).toBeVisible();
		await page.locator('.maplibregl-canvas').tap({ position: { x: 60, y: 300 } });
		await expect(mehr(page)).toHaveAttribute('aria-expanded', 'false');
	});

	test('folgt die Karte dem Fahrzeug, trägt „⋯" einen Punkt', async ({ page }) => {
		await oeffnen(page);
		await expect(mehr(page)).not.toHaveClass(/folgt/);
		await mehr(page).tap();
		await page.getByRole('button', { name: 'Mein Fahrzeug', exact: true }).tap();
		await expect(mehr(page)).toHaveClass(/folgt/);
		await expect(mehr(page)).toHaveAttribute('aria-expanded', 'false');
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

	test('die Kartenknöpfe stehen mit Text da, ohne „⋯"', async ({ page }) => {
		await oeffnen(page);
		await expect(page.locator('.map-ctrl-btn .ctrl-text', { hasText: 'Norden' })).toBeVisible();
		await expect(mehr(page)).toBeHidden();
	});
});
