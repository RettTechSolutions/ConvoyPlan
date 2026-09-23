import { test, expect, type Page } from '@playwright/test';
import {
	blockExternal, fahrzeug, konvoiFahrzeug, mockOrgPortal, mockTrack,
	type FuellstandMeldung, type TrackFahrzeug,
} from './fixtures';

/**
 * Die Zusagen zum Füllstand von Tank bzw. Akku:
 *
 * - Eine **Meldung** und der **eingetragene Stand aus der Planung** sehen
 *   verschieden aus — Letzterer trägt „laut Planung" im Text. Sonst hielte die
 *   Führung einen Stand vom Vortag für eine Meldung von unterwegs.
 * - `0 %` ist eine Meldung („leer") und keine fehlende Angabe.
 * - Gemeldet wird erst auf Knopfdruck, als ganze Zahl — die Schnellwahl füllt
 *   nur das Feld.
 * - Eine Meldung, die nicht ankam, steht nicht auf dem Schirm.
 */

const SLUG = '6dA4KrUG';

async function oeffnen(page: Page, fahrzeuge: TrackFahrzeug[], scope: 'track' | 'driver' = 'track') {
	await blockExternal(page);
	await mockTrack(page, { scope, fahrzeuge });
	await page.goto(`/track/${SLUG}`, { waitUntil: 'domcontentloaded' });
}

const fuellstand = (page: Page, id = 'v1') => page.getByTestId(`fuellstand-${id}`);

test.describe('Füllstand in der Fahrzeugliste', () => {
	test('eine Meldung steht mit Litern und Reichweite da', async ({ page }) => {
		await oeffnen(page, [
			fahrzeug({
				propulsion: 'combustion', tank_capacity_l: 80, fuel_consumption_l100km: 12.5,
				current_fuel_l: 70, fuellstand_ist_prozent: 50,
			}),
		]);

		const feld = fuellstand(page);
		// Die Meldung schlägt den eingetragenen Stand (70 l).
		await expect(feld).toContainText('Tank 50 % · ≈ 40 l · ≈ 320 km');
		await expect(feld).not.toContainText('laut Planung');
	});

	test('ohne Meldung steht der eingetragene Stand — ausdrücklich als Planung', async ({ page }) => {
		await oeffnen(page, [
			fahrzeug({ propulsion: 'combustion', tank_capacity_l: 80, current_fuel_l: 45 }),
		]);

		await expect(fuellstand(page)).toContainText('Tank 45 von 80 l (56 %) · laut Planung');
	});

	test('ohne jede Angabe steht nichts da', async ({ page }) => {
		await oeffnen(page, [fahrzeug()]);

		await expect(page.locator('.vehicle-row')).toBeVisible();
		await expect(fuellstand(page)).toHaveCount(0);
	});

	test('ein E-Fahrzeug zeigt Akku und Kilowattstunden mit Dezimalkomma', async ({ page }) => {
		await oeffnen(page, [
			fahrzeug({
				propulsion: 'electric', battery_capacity_kwh: 77, consumption_kwh_100km: 18,
				fuellstand_ist_prozent: 50,
			}),
		]);

		await expect(fuellstand(page)).toContainText('Akku 50 % · ≈ 38,5 kWh · ≈ 214 km');
	});

	test('0 % ist eine Meldung — und eine Warnung', async ({ page }) => {
		await oeffnen(page, [
			fahrzeug({ propulsion: 'combustion', tank_capacity_l: 80, current_fuel_l: 60, fuellstand_ist_prozent: 0 }),
		]);

		const feld = fuellstand(page);
		await expect(feld).toContainText('Tank 0 %');
		await expect(feld).not.toContainText('laut Planung');
		// Farbe allein trägt die Aussage nicht — sie steht im Titel.
		await expect(feld).toHaveAttribute('title', /Tankstopp/);
	});
});

test.describe('Füllstand melden (Fahrer-Link)', () => {
	test('die Schnellwahl füllt nur das Feld, gemeldet wird auf Knopfdruck — als Zahl', async ({ page }) => {
		const gesendet: string[] = [];
		await page.routeWebSocket(/\/api\/ws\/track\//, (ws) => {
			ws.onMessage((nachricht) => gesendet.push(String(nachricht)));
		});
		await oeffnen(page, [fahrzeug({ id: 'v1', name: 'LF 10', tank_capacity_l: 80 })], 'driver');

		await page.getByLabel('Fahrzeug').selectOption('v1');
		const form = page.getByTestId('fuellstand-form-fahrer');
		await form.getByRole('button', { name: '½', exact: true }).click();
		await expect(form.getByLabel('Füllstand in %')).toHaveValue('50');

		// Die Stellung zu wählen ist noch keine Meldung.
		expect(gesendet.filter((f) => f.includes('fuellstand'))).toHaveLength(0);

		await form.getByRole('button', { name: /Füllstand melden/ }).click();

		await expect.poll(() => gesendet.filter((f) => f.includes('fuellstand')).length).toBe(1);
		const rahmen = JSON.parse(gesendet.find((f) => f.includes('fuellstand'))!);
		expect(rahmen).toEqual({ type: 'fuellstand', vehicle_id: 'v1', prozent: 50 });
		// Eine Zahl, keine Zeichenkette — sonst verwirft das Backend die Meldung.
		expect(typeof rahmen.prozent).toBe('number');
		// Die eigene Meldung steht sofort in der eigenen Liste.
		await expect(fuellstand(page)).toContainText('Tank 50 % · ≈ 40 l');
	});

	test('ein eingetippter Wert wird auf eine ganze Zahl bis 100 gebracht', async ({ page }) => {
		const gesendet: string[] = [];
		await page.routeWebSocket(/\/api\/ws\/track\//, (ws) => {
			ws.onMessage((nachricht) => gesendet.push(String(nachricht)));
		});
		await oeffnen(page, [fahrzeug({ id: 'v1', name: 'LF 10' })], 'driver');

		await page.getByLabel('Fahrzeug').selectOption('v1');
		const form = page.getByTestId('fuellstand-form-fahrer');
		await form.getByLabel('Füllstand in %').fill('120');
		await form.getByRole('button', { name: /Füllstand melden/ }).click();

		await expect.poll(() => gesendet.filter((f) => f.includes('fuellstand')).length).toBe(1);
		expect(JSON.parse(gesendet.find((f) => f.includes('fuellstand'))!).prozent).toBe(100);
	});

	test('eine Meldung eines anderen Fahrzeugs erscheint live', async ({ page }) => {
		await page.routeWebSocket(/\/api\/ws\/track\//, (ws) => {
			ws.send(JSON.stringify({
				type: 'fuellstand_update', vehicle_id: 'v2', prozent: 20,
				gemeldet_at: '2026-09-18T14:30:00+00:00',
			}));
		});
		await oeffnen(page, [
			fahrzeug({ id: 'v1', name: 'LF 10' }),
			fahrzeug({ id: 'v2', name: 'MTW 2', position: 2, tank_capacity_l: 60 }),
		]);

		await expect(fuellstand(page, 'v2')).toContainText('Tank 20 % · ≈ 12 l');
		await expect(fuellstand(page, 'v2')).toHaveAttribute('title', /unter ¼/);
	});
});

test.describe('Füllstand nachtragen (Tracking-Ansicht)', () => {
	const SLUG_ORG = 'thw-musterstadt';
	const CONVOY = '11111111-1111-1111-1111-111111111111';

	function verband() {
		return [
			konvoiFahrzeug({
				position: 1, fuellstand_ist_prozent: 75,
				vehicle: { id: 'v1', name: 'LF 10', callsign: 'Florian 1', propulsion: 'combustion', tank_capacity_l: 80 },
			}),
			konvoiFahrzeug({
				position: 2,
				vehicle: {
					id: 'v2', name: 'MTW 2', callsign: 'Florian 2', propulsion: 'combustion',
					tank_capacity_l: 60, fuel_consumption_l100km: 10, current_fuel_l: 30,
				},
			}),
		];
	}

	async function oeffnenAlsOrg(
		page: Page,
		opts: { rolle?: 'beobachter' | 'fahrer' | 'planer' | 'admin'; fuellstandFehler?: boolean } = {},
	) {
		await blockExternal(page);
		const meldungen: FuellstandMeldung[] = [];
		await mockOrgPortal(page, {
			slug: SLUG_ORG, convoyId: CONVOY, fahrzeuge: verband(),
			rolle: opts.rolle, fuellstandMeldungen: meldungen, fuellstandFehler: opts.fuellstandFehler,
		});
		await page.goto(`/o/${SLUG_ORG}/tracking/${CONVOY}`, { waitUntil: 'domcontentloaded' });
		return meldungen;
	}

	test('die Führung trägt einen über Funk gemeldeten Füllstand nach', async ({ page }) => {
		const meldungen = await oeffnenAlsOrg(page);

		await expect(fuellstand(page, 'v2')).toContainText('laut Planung');

		await page.getByTestId('fuellstand-edit-v2').click();
		const form = page.getByTestId('fuellstand-form-v2');
		await form.getByRole('button', { name: '¼', exact: true }).click();
		expect(meldungen).toHaveLength(0);

		await form.getByRole('button', { name: /Füllstand eintragen/ }).click();

		await expect.poll(() => meldungen.length).toBe(1);
		// An das Fahrzeug der Zeile, nicht an das erste im Verband.
		expect(meldungen[0]).toEqual({ fahrzeugId: 'v2', prozent: 25 });
		await expect(fuellstand(page, 'v2')).toContainText('Tank 25 % · ≈ 15 l · ≈ 150 km');
		await expect(fuellstand(page, 'v2')).not.toContainText('laut Planung');
	});

	test('das Feld startet bei der bestehenden Meldung — und ohne eine leer', async ({ page }) => {
		await oeffnenAlsOrg(page);

		await page.getByTestId('fuellstand-edit-v1').click();
		await expect(page.getByTestId('fuellstand-form-v1').getByLabel('Füllstand in %')).toHaveValue('75');

		// v2 hat nur den eingetragenen Stand (50 %). Stünde er im Feld, wäre
		// die bequemste Antwort „wie geplant" — und die Meldung wertlos.
		await page.getByTestId('fuellstand-edit-v2').click();
		const offen = page.getByTestId('fuellstand-form-v2');
		await expect(offen.getByLabel('Füllstand in %')).toHaveValue('');
		await expect(offen.getByRole('button', { name: /Füllstand eintragen/ })).toBeDisabled();
	});

	test('scheitert die Meldung, wird die Anzeige zurückgenommen', async ({ page }) => {
		await oeffnenAlsOrg(page, { fuellstandFehler: true });

		await page.getByTestId('fuellstand-edit-v1').click();
		const form = page.getByTestId('fuellstand-form-v1');
		await form.getByRole('button', { name: 'Reserve', exact: true }).click();
		await form.getByRole('button', { name: /Füllstand eintragen/ }).click();

		await expect(page.getByText('Füllstand konnte nicht gemeldet werden')).toBeVisible();
		await expect(fuellstand(page, 'v1')).toContainText('Tank 75 %');
	});

	test('ein Beobachter sieht den Füllstand, kann ihn aber nicht setzen', async ({ page }) => {
		await oeffnenAlsOrg(page, { rolle: 'beobachter' });

		await expect(fuellstand(page, 'v1')).toContainText('Tank 75 % · ≈ 60 l');
		await expect(page.getByTestId('fuellstand-edit-v1')).toHaveCount(0);

		await page.getByRole('button', { name: 'Status', exact: true }).click();
		await expect(page.getByTestId('fuellstand-form-eigen')).toHaveCount(0);
	});

	test('der eigene Füllstand geht an das unter „Meine Position" gewählte Fahrzeug', async ({ page }) => {
		const meldungen = await oeffnenAlsOrg(page);

		await page.getByLabel('Meine Position').selectOption('v2');
		await page.getByRole('button', { name: 'Status', exact: true }).click();

		const form = page.getByTestId('fuellstand-form-eigen');
		await form.getByLabel('Füllstand in %').fill('40');
		await form.getByRole('button', { name: /Füllstand melden/ }).click();

		await expect.poll(() => meldungen.length).toBe(1);
		expect(meldungen[0]).toEqual({ fahrzeugId: 'v2', prozent: 40 });
		await expect(form.getByText('Füllstand gemeldet')).toBeVisible();
	});
});
