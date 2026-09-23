import { test, expect, type Page } from '@playwright/test';
import { blockExternal, fahrzeug, mockTrack, type TrackFahrzeug } from './fixtures';

/**
 * Die Betriebsstofflage in der Fahrzeugliste.
 *
 * Gemeldet wird sie aus der Companion-App über den Fahrer-Link; hier wird
 * geprüft, was die Führung davon abliest. Die Zusagen: ohne Meldung steht
 * nichts da, was sich als Füllstand lesen ließe; ein knapper Tank ist als
 * solcher benannt — nicht nur eingefärbt —, und eine Meldung aus dem Kanal
 * erscheint ohne Neuladen.
 */

const SLUG = '6dA4KrUG';

async function oeffnen(page: Page, fahrzeuge: TrackFahrzeug[]) {
	await blockExternal(page);
	await mockTrack(page, { scope: 'track', fahrzeuge });
	await page.goto(`/track/${SLUG}`, { waitUntil: 'domcontentloaded' });
}

const lage = (page: Page, id = 'v1') => page.getByTestId(`betriebsstoff-${id}`);

test.describe('Betriebsstoff in der Fahrzeugliste', () => {
	test('ohne Meldung steht nichts da', async ({ page }) => {
		await oeffnen(page, [fahrzeug()]);

		await expect(page.getByTestId('staerke-v1')).toBeVisible();
		await expect(lage(page)).toHaveCount(0);
	});

	test('eine Meldung zeigt Füllstand und nennt die Reichweite', async ({ page }) => {
		await oeffnen(page, [
			fahrzeug({ betriebsstoff_verbrauch: 30, betriebsstoff_tank: 200, betriebsstoff_fuellstand: 50 }),
		]);

		await expect(lage(page)).toContainText('50 %');
		// 100 l bei 30 l/100 km
		await expect(lage(page)).toHaveAttribute('title', /Reichweite etwa 333 km/);
	});

	test('ein leerer Tank ist eine Meldung und keine Lücke', async ({ page }) => {
		await oeffnen(page, [fahrzeug({ betriebsstoff_fuellstand: 0 })]);

		await expect(lage(page)).toContainText('0 %');
	});

	test('ein knapper Tank ist benannt, nicht nur eingefärbt', async ({ page }) => {
		await oeffnen(page, [
			fahrzeug({ id: 'v1', name: 'LF 10', betriebsstoff_fuellstand: 20 }),
			fahrzeug({ id: 'v2', name: 'MTW 2', betriebsstoff_fuellstand: 80 }),
		]);

		await expect(lage(page, 'v1')).toHaveClass(/knapp/);
		await expect(lage(page, 'v1')).toHaveAttribute('title', /Füllstand 20 %/);
		await expect(lage(page, 'v2')).not.toHaveClass(/knapp/);
	});

	test('fehlen Tank und Verbrauch in der Meldung, rechnet die Reichweite mit den Stammdaten', async ({ page }) => {
		await oeffnen(page, [
			fahrzeug({ tank_capacity_l: 300, fuel_consumption_l100km: 30, betriebsstoff_fuellstand: 50 }),
		]);

		// 150 l bei 30 l/100 km — und woher die Zahlen kommen, steht dabei.
		await expect(lage(page)).toHaveAttribute('title', /Reichweite etwa 500 km/);
		await expect(lage(page)).toHaveAttribute('title', /Stammdaten/);
	});

	test('bei einem E-Fahrzeug wird nicht gegen Liter gerechnet', async ({ page }) => {
		await oeffnen(page, [
			fahrzeug({ propulsion: 'electric', tank_capacity_l: 300, fuel_consumption_l100km: 30, betriebsstoff_fuellstand: 50 }),
		]);

		await expect(lage(page)).toContainText('50 %');
		await expect(lage(page)).not.toHaveAttribute('title', /Reichweite/);
	});

	test('eine Meldung aus dem Kanal erscheint ohne Neuladen', async ({ page }) => {
		await page.routeWebSocket(/\/api\/ws\/track\//, (ws) => {
			ws.send(JSON.stringify({
				type: 'betriebsstoff_update', vehicle_id: 'v1',
				verbrauch: 25, tank: 100, fuellstand: 75, gemeldet_at: '2026-09-23T06:00:00+00:00',
			}));
		});
		await oeffnen(page, [fahrzeug()]);

		await expect(lage(page)).toContainText('75 %');
		await expect(lage(page)).toHaveAttribute('title', /Reichweite etwa 300 km/);
	});
});
