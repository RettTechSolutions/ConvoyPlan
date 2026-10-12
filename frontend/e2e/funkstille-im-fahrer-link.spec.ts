import { test, expect, type Page, type WebSocketRoute } from '@playwright/test';
import { blockExternal, fahrzeug, mockTrack } from './fixtures';

// Funkstille im Fahrer-Link: die Besatzung dahinter merkt als Erste, wenn der
// Vordermann fehlt. Zusagen, die man einem Bildschirmfoto nicht ansieht:
//
// - Gemeldet wird nur, wer fuhr. Ein stehendes Fahrzeug schweigt zu Recht.
// - Das eigene Fahrzeug zählt nicht — dessen Ausfall zeigt die Verbindungsanzeige.
// - Der öffentliche Kanal beantwortet keine Pings. Schweigt er ganz, lässt sich
//   die eigene Funkstille nicht von der der anderen trennen: keine Meldung.

const ROLLE = fahrzeug({ id: 'v1', name: 'ELW 1', callsign: 'Akkon 10/1', vehicle_status: 'en_route', position: 1 });
const MTW = fahrzeug({ id: 'v2', name: 'MTW', callsign: 'Akkon 14/1', vehicle_status: 'en_route', position: 2 });
const KTW = fahrzeug({ id: 'v3', name: 'KTW', callsign: 'Akkon 85/1', vehicle_status: 'en_route', position: 3 });
const RTW = fahrzeug({ id: 'v4', name: 'RTW', callsign: 'Akkon 83/1', vehicle_status: 'en_route', position: 4 });

async function oeffnen(page: Page) {
	await page.clock.install();
	let kanal: WebSocketRoute | null = null;
	await blockExternal(page);
	await page.routeWebSocket(/\/api\/ws\/track\//, (ws) => {
		kanal = ws;
		ws.onMessage(() => { /* Belegung, eigene Positionen — hier ohne Antwort */ });
		ws.send(JSON.stringify({ type: 'belegungen', vehicle_ids: [] }));
	});
	await mockTrack(page, { scope: 'driver', fahrzeuge: [ROLLE, MTW, KTW, RTW] });
	await page.goto('/track/fUnKsTiLlE', { waitUntil: 'domcontentloaded' });
	await page.getByLabel('Fahrzeug').selectOption('v1');
	await expect.poll(() => kanal !== null).toBe(true);
	const senden = (id: string, lat: number, kmh: number) => kanal!.send(JSON.stringify({
		vehicle_id: id, lat, lon: 8.69, speed_kmh: kmh, heading: 0, recorded_at: new Date().toISOString(),
	}));
	// Die Uhr in Schritten; `rtw` sendet dabei weiter, wenn gewünscht — das
	// Lebenszeichen des Kanals in einem fahrenden Verband.
	const vergehen = async (ms: number, { rtw = false } = {}) => {
		for (let t = 0; t < ms; t += 5_000) {
			if (rtw) senden('v4', 50.04, 40);
			await page.clock.runFor(Math.min(5_000, ms - t));
		}
	};
	return { senden, vergehen };
}

test('der fehlende Vordermann wird gemeldet, das eigene und das stehende Fahrzeug nicht', async ({ page }) => {
	const { senden, vergehen } = await oeffnen(page);
	const banner = page.getByTestId('funkstille-banner');
	senden('v1', 50.06, 50); // das eigene
	senden('v2', 50.055, 60);
	senden('v3', 50.05, 0); // steht
	await expect(page.locator('.maplibregl-marker').filter({ hasText: 'Akkon 14/1' })).toBeVisible();

	await vergehen(150_000, { rtw: true });
	await expect(banner).toHaveCount(0);

	await vergehen(40_000, { rtw: true });
	await expect(banner).toBeVisible();
	await expect(banner).toContainText('Funkstille: Akkon 14/1 · keine Position, zuletzt 60 km/h');
	await expect(banner).not.toContainText('weitere');

	await banner.getByRole('button', { name: 'Letzte Position' }).click();
	await expect(page.locator('.fz-blase strong')).toHaveText('Akkon 14/1');
	await expect(page.locator('.fz-blase')).toContainText('Funkstille: keine Position seit 3 min');

	// Ausgeblendet bleibt sie weg, bis wieder eine Position kommt.
	await banner.getByRole('button', { name: 'Ausblenden' }).click();
	await expect(banner).toHaveCount(0);
	senden('v2', 50.056, 55);
	await vergehen(10_000, { rtw: true });
	await vergehen(185_000, { rtw: true });
	await expect(banner).toBeVisible();
});

test('schweigt der ganze Kanal, gibt es keine Meldung', async ({ page }) => {
	const { senden, vergehen } = await oeffnen(page);
	senden('v2', 50.055, 60);
	await expect(page.locator('.maplibregl-marker').filter({ hasText: 'Akkon 14/1' })).toBeVisible();
	await vergehen(240_000);
	await expect(page.getByTestId('funkstille-banner')).toHaveCount(0);
});
