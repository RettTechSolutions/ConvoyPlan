import { test, expect, type Page } from '@playwright/test';
import { fileURLToPath } from 'node:url';
import { fahrzeug, mockTrack, position, stubPrint, trackPayload } from '../e2e/fixtures';

// Bilder zum Fahrer-Link und zum Teilen-Dialog für die Handbücher
// (`docs/handbuecher/build.py`, Kapitel Live-Tracking und Teilen).
// Erzeugt mit `npm run wiki:bilder` (siehe `playwright.wiki.config.ts`).
//
// Gestellt wie in den E2E-Tests, nicht von einer echten Instanz: Ein Fahrer-Link
// dort hieße, einen Link anzulegen, der Positionen freigibt — für ein Bild nicht
// wert. Die Namen sind ausgedacht.

const ZIEL = fileURLToPath(new URL('../../docs/handbuecher/bilder/', import.meta.url));
const HUELLE = 'http://localhost:4174/';

const kacheln = new Map<string, Buffer>();
async function osmKacheln(page: Page) {
	await page.route('**/api/tiles/**', async (route) => {
		const pfad = new URL(route.request().url()).pathname.replace('/api/tiles/', '');
		let bild = kacheln.get(pfad);
		if (!bild) {
			const antwort = await route.fetch({
				url: `https://tile.openstreetmap.org/${pfad}`,
				headers: { 'User-Agent': 'ConvoyPlan-Wiki-Bilder (https://github.com/RettTechSolutions/ConvoyPlan)' },
			});
			bild = await antwort.body();
			kacheln.set(pfad, bild);
		}
		await route.fulfill({ body: bild, contentType: 'image/png' });
	});
}

async function karteGeladen(page: Page) {
	await page.waitForFunction(() =>
		performance.getEntriesByType('resource').filter((r) => r.name.includes('/api/tiles/')).length > 8,
	);
	await page.waitForLoadState('networkidle');
	await page.waitForTimeout(800);
}

async function bild(page: Page, datei: string, clip?: { x: number; y: number; width: number; height: number }) {
	await page.mouse.move(1, 1);
	await page.screenshot({ path: `${ZIEL}${datei}`, clip, animations: 'disabled', type: 'jpeg', quality: 82 });
}

/** Nur die Dialoge: Hinter ihnen steht in der Hülle ein Platzhalter, keine App. */
async function dialoge(page: Page, rand = 24) {
	const boxen = await Promise.all((await page.getByRole('dialog').all()).map(async (d) => (await d.boundingBox())!));
	const x = Math.max(0, Math.min(...boxen.map((b) => b.x)) - rand);
	const y = Math.max(0, Math.min(...boxen.map((b) => b.y)) - rand);
	const r = Math.max(...boxen.map((b) => b.x + b.width)) + rand;
	const u = Math.max(...boxen.map((b) => b.y + b.height)) + rand;
	return { x, y, width: r - x, height: u - y };
}

// Frankfurt → Kassel über die A5/A7, grob genug für eine Übersicht.
const LINIE: [number, number][] = [
	[8.682, 50.11], [8.70, 50.20], [8.74, 50.30], [8.80, 50.40], [8.86, 50.50],
	[8.95, 50.60], [9.10, 50.70], [9.30, 50.78], [9.45, 50.86], [9.50, 50.98],
	[9.46, 51.10], [9.44, 51.20], [9.48, 51.31],
];

const FAHRZEUGE = [
	fahrzeug({ id: 'v1', name: 'ELW 1', callsign: 'Musterstadt 10/1', sonderfunktion: 'Führung', position: 1, vehicle_status: 'en_route',
		staerke_soll_fuehrer: 1, staerke_soll_unterfuehrer: 1, staerke_soll_mannschaften: 1,
		staerke_ist_fuehrer: 1, staerke_ist_unterfuehrer: 1, staerke_ist_mannschaften: 1, betriebsstoff_fuellstand: 78 }),
	fahrzeug({ id: 'v2', name: 'MTW', callsign: 'Musterstadt 14/1', sonderfunktion: null, position: 2, vehicle_status: 'en_route',
		staerke_soll_fuehrer: 0, staerke_soll_unterfuehrer: 1, staerke_soll_mannschaften: 7,
		staerke_ist_fuehrer: 0, staerke_ist_unterfuehrer: 1, staerke_ist_mannschaften: 5, betriebsstoff_fuellstand: 64 }),
	fahrzeug({ id: 'v3', name: 'RTW', callsign: 'Musterstadt 83/1', sonderfunktion: null, position: 3, vehicle_status: 'en_route',
		staerke_soll_fuehrer: 0, staerke_soll_unterfuehrer: 1, staerke_soll_mannschaften: 1, betriebsstoff_fuellstand: 71 }),
	fahrzeug({ id: 'v4', name: 'GW-San', callsign: 'Musterstadt 19/1', sonderfunktion: 'Schlussfahrzeug', position: 4, vehicle_status: 'planned' }),
];

async function fahrerLink(page: Page) {
	await mockTrack(page, {
		scope: 'driver',
		fahrzeuge: FAHRZEUGE,
		positionen: [
			{ ...position('v1'), lat: 50.40, lon: 8.80, recorded_at: new Date().toISOString() },
			{ ...position('v2'), lat: 50.385, lon: 8.79, recorded_at: new Date().toISOString() },
			{ ...position('v3'), lat: 50.37, lon: 8.78, recorded_at: new Date().toISOString() },
		],
	});
	// Die Nutzlast der Fixture, mit Route und Wegpunkten statt einem einzelnen Punkt.
	await page.route('**/api/track/*', async (route) => {
		const p = trackPayload('driver', FAHRZEUGE, [
			{ ...position('v1'), lat: 50.40, lon: 8.80, recorded_at: new Date().toISOString() },
			{ ...position('v2'), lat: 50.385, lon: 8.79, recorded_at: new Date().toISOString() },
			{ ...position('v3'), lat: 50.37, lon: 8.78, recorded_at: new Date().toISOString() },
		]);
		await route.fulfill({
			json: {
				...p,
				name: 'Übungsmarsch Nord',
				organization: 'Hilfsorganisation Musterstadt',
				start_time: new Date(Date.now() - 50 * 60_000).toISOString(),
				geojson: { type: 'LineString', coordinates: LINIE },
				distance_m: 214_900,
				waypoints: [
					{ name: 'Start', type: 'start', lat: 50.11, lon: 8.682, planned_arrival: null, planned_departure: null, halt_purpose: null },
					{ name: 'KP 1 – Gambacher Kreuz', type: 'checkpoint', lat: 50.50, lon: 8.86, planned_arrival: null, planned_departure: null, halt_purpose: null },
					{ name: 'Tankhalt – Raststätte', type: 'stop', lat: 50.78, lon: 9.30, planned_arrival: null, planned_departure: null, halt_purpose: 'tanken' },
					{ name: 'Ziel', type: 'destination', lat: 51.31, lon: 9.48, planned_arrival: null, planned_departure: null, halt_purpose: null },
				],
			},
		});
	});
	await page.routeWebSocket(/\/api\/ws\//, () => {});
	await page.route('**/api/setup/status', (r) => r.fulfill({ json: { setup_required: false } }));
	await osmKacheln(page);
	await page.goto('/track/Bsp4Fahr', { waitUntil: 'domcontentloaded' });
	await expect(page.locator('.map-ctrl-btn').first()).toBeVisible();
	await karteGeladen(page);
}

test.describe('Fahrer-Link am Telefon', () => {
	test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, deviceScaleFactor: 3 });

	test('Karte und eigenes Fahrzeug', async ({ page }) => {
		await fahrerLink(page);
		await bild(page, 'fahrer-tel-karte.jpg');

		await page.getByRole('button', { name: 'Menü', exact: true }).click();
		await page.locator('.sidebar select').first().selectOption('v2');
		await page.waitForTimeout(800);
		await bild(page, 'fahrer-tel-schublade.jpg');
	});
});

test('Fahrer-Link am Schreibtisch', async ({ page }) => {
	await fahrerLink(page);
	await page.locator('.sidebar select').first().selectOption('v2').catch(() => {});
	await page.waitForTimeout(800);
	await bild(page, 'fahrer-desktop.jpg');
});

test('Teilen-Dialog und QR-Code', async ({ page }) => {
	await stubPrint(page);
	await page.goto(HUELLE);
	await expect(page.getByRole('heading', { name: 'Live-Tracking teilen' })).toBeVisible();
	await bild(page, 'teilen-dialog.jpg', await dialoge(page));
	await page.getByTitle('QR-Code anzeigen').first().click();
	await expect(page.getByRole('heading', { name: /QR-Code · / })).toBeVisible();
	await page.waitForTimeout(400);
	await bild(page, 'teilen-qr.jpg', await dialoge(page));
});
