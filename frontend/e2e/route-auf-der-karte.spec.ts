import { test, expect } from '@playwright/test';
import { CONVOY, planung, tab } from './kontextmenue-attrappe';

// „Route berechnen" auf der Karte, außerhalb des Reiters Plan. Die Zusagen:
//  - im Reiter Plan steht er nicht noch einmal — dort gibt es den großen Knopf;
//  - in jedem anderen Reiter schwebt er links unten über der Karte und sagt,
//    ob er zum ersten Mal oder neu berechnet;
//  - er schickt dieselbe Berechnung wie der Knopf im Reiter Plan, und wer
//    gerade Wegpunkte bearbeitet, bleibt danach dort;
//  - am Telefon steht er nicht — dort gibt es den FAB rechts unten.

const ROUTE = {
	id: 'route-1', convoy_id: CONVOY, distance_m: 412_000, duration_s: 16_200,
	routing_params: null, fuel_analysis: null, kanalwechsel: [],
	durchfahrtshoehen: [], gewichtsgrenzen: [],
	geojson: { type: 'LineString', coordinates: [[9.93, 49.79], [11.03, 50.98], [12.37, 51.34]] },
};

const knopf = (page: import('@playwright/test').Page) => page.locator('.map-area').getByRole('button', { name: /Route (neu )?berechnen/ });

test('außerhalb des Reiters Plan steht der Knopf auf der Karte und rechnet, ohne den Reiter zu wechseln', async ({ page }) => {
	await planung(page);
	// Nach `planung`: die zuletzt eingehängte Route gewinnt.
	await page.route(`**/api/convoys/${CONVOY}/calculate-route`, (r) => r.fulfill({ json: ROUTE }));

	await expect(knopf(page)).toHaveCount(0);

	await tab(page, 'Wegpunkte').click();
	await expect(knopf(page)).toHaveText('🗺 Route berechnen');
	const box = (await knopf(page).boundingBox())!;
	const karte = (await page.locator('.map-area').boundingBox())!;
	// Links unten.
	expect(box.x - karte.x).toBeLessThan(40);
	expect(karte.y + karte.height - (box.y + box.height)).toBeLessThan(80);

	const anfrage = page.waitForRequest(`**/api/convoys/${CONVOY}/calculate-route`);
	await knopf(page).click();
	expect((await anfrage).method()).toBe('POST');
	await expect(knopf(page)).toHaveText('↻ Route neu berechnen');
	await expect(tab(page, 'Wegpunkte')).toHaveClass(/active/);
});

test('am Telefon steht er nicht auf der Karte', async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await planung(page);
	await expect(page.locator('.karte-route')).toHaveCount(0);
	// Auch nicht versteckt in einem anderen Reiter: per CSS aus.
	await page.locator('.tab', { hasText: 'Wegpunkte' }).first().evaluate((el: HTMLElement) => el.click());
	await expect(page.locator('.karte-route')).toBeHidden();
});
