import { test, expect, type Page, type WebSocketRoute } from '@playwright/test';
import { blockExternal, konvoiFahrzeug, mockOrgPortal } from './fixtures';

// Die Blase am Fahrzeug auf der Karte. Zusagen, die man einem Bildschirmfoto
// nicht ansieht:
//
// - Sie trägt, was die Fahrzeugzeile trägt — Status, Stärke, Betriebsstoff,
//   Tracker —, damit die Führung auf der Karte nicht zur Leiste wechseln muss.
// - Sie bleibt aktuell, solange sie offen ist. Vorher entstand sie einmal mit
//   der Marke, und das Tempo darin blieb stehen, während das Fahrzeug fuhr.

const SLUG = 'blase-org';
const CONVOY = 'c-blase';

async function oeffnen(page: Page): Promise<() => WebSocketRoute> {
	let kanal: WebSocketRoute | null = null;
	await blockExternal(page);
	await page.routeWebSocket(/\/api\/ws\//, (ws) => { kanal = ws; });
	await mockOrgPortal(page, {
		slug: SLUG, convoyId: CONVOY, rolle: 'planer',
		fahrzeuge: [
			konvoiFahrzeug({
				position: 1,
				vehicle_status: 'en_route',
				staerke_soll_fuehrer: 0, staerke_soll_unterfuehrer: 1, staerke_soll_mannschaften: 7,
				staerke_ist_fuehrer: 0, staerke_ist_unterfuehrer: 1, staerke_ist_mannschaften: 5,
				betriebsstoff_verbrauch: 30, betriebsstoff_tank: 200, betriebsstoff_fuellstand: 14,
				vehicle: { id: 'v-mtw', name: 'MTW', callsign: 'Akkon 14/1' },
			}),
		],
		tracker: [
			{ vehicle_id: 'v-mtw', zuletzt_gesehen: new Date().toISOString(), akku_prozent: 64,
			  extern: true, akku_seit: null, akku_niedrig: false, signal_dbm: -85 },
		],
	});
	await page.goto(`/o/${SLUG}/tracking/${CONVOY}`, { waitUntil: 'domcontentloaded' });
	await expect.poll(() => kanal !== null).toBe(true);
	return () => kanal!;
}

function position(speed: number) {
	return JSON.stringify({
		vehicle_id: 'v-mtw', lat: 50.12, lon: 8.69, speed_kmh: speed, heading: 30,
		recorded_at: new Date().toISOString(), quelle: 'tracker',
	});
}

test('die Blase zeigt die Live-Angaben des Fahrzeugs und bleibt aktuell', async ({ page }) => {
	const kanal = await oeffnen(page);
	kanal().send(position(50));

	const marke = page.locator('.maplibregl-marker').filter({ hasText: 'Akkon 14/1' });
	await expect(marke).toBeVisible();
	await marke.click();

	const blase = page.locator('.fz-blase');
	await expect(blase).toBeVisible();
	await expect(blase.locator('strong')).toHaveText('Akkon 14/1');
	await expect(blase).toContainText('50 km/h');
	await expect(blase).toContainText('Tracker');
	await expect(blase).toContainText('MTW');
	await expect(blase).toContainText('Unterwegs');

	// Abweichung vom Soll und knapper Betriebsstoff stehen hervorgehoben da.
	const staerke = blase.locator('div', { hasText: /^Stärke 0\/1\/5\/\/6 \(Soll 0\/1\/7\/\/8\)$/ });
	await expect(staerke).toHaveClass(/warnung/);
	await expect(blase.locator('div.warnung', { hasText: 'Betriebsstoff 14 % · Reichweite etwa 93 km' })).toBeVisible();
	await expect(blase).toContainText('Tracker: Akku 64 % · am Bordnetz');

	// Neue Position und neuer Status bei offener Blase.
	kanal().send(position(72));
	kanal().send(JSON.stringify({
		type: 'status_update', vehicle_id: 'v-mtw', vehicle_status: 'technical_halt', status_level: 'dringend',
	}));
	await expect(blase).toContainText('72 km/h');
	await expect(blase).not.toContainText('50 km/h');
	await expect(blase.locator('div.warnung', { hasText: /^Techn\. Halt · / })).toBeVisible();
});
