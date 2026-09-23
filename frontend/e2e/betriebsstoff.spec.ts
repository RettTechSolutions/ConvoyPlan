import { test, expect, type Page } from '@playwright/test';
import {
	blockExternal, fahrzeug, konvoiFahrzeug, mockOrgPortal, mockTrack,
	type BetriebsstoffMeldung, type TrackFahrzeug,
} from './fixtures';

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

test.describe('Betriebsstoff nachtragen (Tracking-Ansicht)', () => {
	const SLUG_ORG = 'thw-musterstadt';
	const CONVOY = '11111111-1111-1111-1111-111111111111';

	function verband() {
		return [
			konvoiFahrzeug({
				position: 1,
				betriebsstoff_verbrauch: 30, betriebsstoff_tank: 200, betriebsstoff_fuellstand: 60,
				vehicle: { id: 'v1', name: 'LF 10', callsign: 'Florian 1' },
			}),
			konvoiFahrzeug({
				position: 2,
				vehicle: {
					id: 'v2', name: 'MTW 2', callsign: 'Florian 2',
					propulsion: 'combustion', tank_capacity_l: 80, fuel_consumption_l100km: 12.5,
				},
			}),
			konvoiFahrzeug({
				position: 3,
				vehicle: { id: 'v3', name: 'E-KdoW', callsign: 'Florian 3', propulsion: 'electric' },
			}),
		];
	}

	async function oeffnenAlsOrg(page: Page, rolle?: 'beobachter' | 'fahrer' | 'planer' | 'admin') {
		const meldungen: BetriebsstoffMeldung[] = [];
		await blockExternal(page);
		await mockOrgPortal(page, {
			slug: SLUG_ORG, convoyId: CONVOY, fahrzeuge: verband(), rolle, betriebsstoffMeldungen: meldungen,
		});
		await page.goto(`/o/${SLUG_ORG}/tracking/${CONVOY}`, { waitUntil: 'domcontentloaded' });
		return meldungen;
	}

	test('die Führung trägt eine Funkmeldung für ein fremdes Fahrzeug nach', async ({ page }) => {
		const meldungen = await oeffnenAlsOrg(page);

		await page.getByTestId('staerke-edit-v2').click();
		const form = page.getByTestId('betriebsstoff-form-v2');
		// Tank und Verbrauch aus den Stammdaten, der Füllstand nie.
		await expect(form.getByLabel('Tank (l)')).toHaveValue('80');
		await expect(form.getByLabel('Verbrauch (l/100 km)')).toHaveValue('12.5');
		await expect(form.getByLabel('Füllstand (%)')).toHaveValue('');

		await form.getByRole('button', { name: '¾' }).click();
		expect(meldungen).toHaveLength(0);
		await form.getByRole('button', { name: /Betriebsstoff eintragen/ }).click();

		await expect.poll(() => meldungen.length).toBe(1);
		expect(meldungen[0]).toEqual({ fahrzeugId: 'v2', verbrauch: 12.5, tank: 80, fuellstand: 75 });
		// Die Liste zeigt die Meldung sofort, ohne Neuladen: 60 l bei 12,5 l/100 km.
		await expect(lage(page, 'v2')).toContainText('75 %');
		await expect(lage(page, 'v2')).toHaveAttribute('title', /Reichweite etwa 480 km/);
	});

	test('eine bestehende Meldung ist der Ausgangsstand der Korrektur', async ({ page }) => {
		await oeffnenAlsOrg(page);

		await page.getByTestId('staerke-edit-v1').click();
		const form = page.getByTestId('betriebsstoff-form-v1');
		await expect(form.getByLabel('Füllstand (%)')).toHaveValue('60');
		await expect(form.getByLabel('Tank (l)')).toHaveValue('200');
	});

	test('eine unplausible Eingabe wird benannt und nicht gesendet', async ({ page }) => {
		const meldungen = await oeffnenAlsOrg(page);

		await page.getByTestId('staerke-edit-v1').click();
		const form = page.getByTestId('betriebsstoff-form-v1');
		await form.getByLabel('Füllstand (%)').fill('140');
		await form.getByRole('button', { name: /Betriebsstoff eintragen/ }).click();

		await expect(form.getByRole('alert')).toContainText('0 bis 100');
		expect(meldungen).toHaveLength(0);
	});

	test('beim E-Fahrzeug gibt es nur den Ladestand', async ({ page }) => {
		const meldungen = await oeffnenAlsOrg(page);

		await page.getByTestId('staerke-edit-v3').click();
		const form = page.getByTestId('betriebsstoff-form-v3');
		await expect(form.getByLabel('Tank (l)')).toHaveCount(0);

		await form.getByLabel('Ladestand (%)').fill('40');
		await form.getByRole('button', { name: /Betriebsstoff eintragen/ }).click();

		await expect.poll(() => meldungen.length).toBe(1);
		expect(meldungen[0]).toEqual({ fahrzeugId: 'v3', verbrauch: null, tank: null, fuellstand: 40 });
	});

	test('ein Beobachter sieht die Lage, kann sie aber nicht nachtragen', async ({ page }) => {
		await oeffnenAlsOrg(page, 'beobachter');

		await expect(lage(page, 'v1')).toContainText('60 %');
		await expect(page.getByTestId('staerke-edit-v1')).toHaveCount(0);
		await expect(page.getByTestId('betriebsstoff-form-v1')).toHaveCount(0);
	});
});
