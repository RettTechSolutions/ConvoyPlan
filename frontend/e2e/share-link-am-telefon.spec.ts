import { test, expect, type Page } from '@playwright/test';
import { GRUNDLAGE, mockApi } from './kontextmenue-attrappe';

// Der öffentliche Share-Link (`/share/<token>`) am Telefon. Er hatte kein
// eigenes Layout: Neben einer 300 px breiten Leiste blieben der Karte 90 px,
// und die OSM-Nennung brach in sechs Zeilen um. Die Zusagen:
//
// - **Am Telefon steht alles untereinander** — Kopf, Karte über die ganze
//   Breite, darunter der Zeitplan — ohne seitliches Scrollen.
// - **Am Schreibtisch bleibt es, wie es war**: Leiste links, Karte rechts.

const TOKEN = 'abc123';
const wp = (id: string, name: string, lat: number, lon: number, an: string, ab: string) => ({
	id, name, lat, lon, type: 'waypoint', order_index: 0, planned_arrival: an, planned_departure: ab,
});

async function oeffnen(page: Page) {
	await mockApi(page, {
		...GRUNDLAGE,
		[`GET /api/convoys/share/${TOKEN}`]: {
			name: 'Verlegung Nord',
			organization: 'THW OV Musterstadt',
			start_time: '2026-10-21T06:00:00Z',
			waypoints: [
				wp('a', 'Fulda', 50.55, 9.68, '2026-10-21T07:10:00Z', '2026-10-21T07:40:00Z'),
				wp('b', 'Erfurt', 50.98, 11.03, '2026-10-21T09:00:00Z', '2026-10-21T09:30:00Z'),
			],
			geojson: { type: 'LineString', coordinates: [[9.68, 50.55], [11.03, 50.98]] },
		},
	});
	await page.goto(`/share/${TOKEN}`);
	await expect(page.getByRole('cell', { name: 'Erfurt' })).toBeVisible();
	await expect(page.locator('.share-map .maplibregl-canvas')).toBeVisible();
}

const kasten = async (page: Page, sel: string) => (await page.locator(sel).first().boundingBox())!;

test.describe('am Telefon', () => {
	test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

	test('Kopf, Karte über die ganze Breite, darunter der Zeitplan', async ({ page }) => {
		await oeffnen(page);
		const kopf = await kasten(page, '.share-kopf');
		const karte = await kasten(page, '.share-map');
		const liste = await kasten(page, '.share-liste');

		expect(karte.width).toBeGreaterThanOrEqual(389);
		expect(karte.height).toBeGreaterThan(300);
		expect(karte.y).toBeGreaterThanOrEqual(kopf.y + kopf.height - 1);
		expect(liste.y).toBeGreaterThanOrEqual(karte.y + karte.height - 1);

		const breite = await page.evaluate(() => document.documentElement.scrollWidth);
		expect(breite, 'kein seitliches Scrollen').toBeLessThanOrEqual(390);
	});
});

test.describe('am Schreibtisch', () => {
	test.use({ viewport: { width: 1280, height: 720 } });

	test('Leiste links, Karte rechts', async ({ page }) => {
		await oeffnen(page);
		const liste = await kasten(page, '.share-liste');
		const karte = await kasten(page, '.share-map');
		expect(liste.width).toBeCloseTo(300, 0);
		expect(karte.x).toBeGreaterThanOrEqual(299);
		expect(karte.height).toBeGreaterThanOrEqual(719);
	});
});
