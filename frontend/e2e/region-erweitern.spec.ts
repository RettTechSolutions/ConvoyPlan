import { test, expect, type Page } from '@playwright/test';

// „Region erweitern": Die Auswahl beginnt mit den Bestandteilen der geladenen
// Karte. Die Zusagen:
//  - übernommen wird jeder Bestandteil, sichtbar als Marke;
//  - Suche und Schnellauswahl fügen hinzu, keine verwirft die übernommenen;
//  - der Wechsel schickt alte und neue Bestandteile zusammen ab;
//  - „Region wechseln" beginnt weiter leer — wer neu anfangen will, kann das.

const HUELLE = 'http://localhost:4174';
const geo = (id: string) => `https://download.geofabrik.de/${id}-latest.osm.pbf`;
const marken = (page: Page) => page.locator('.chip');

async function oeffnen(page: Page) {
	await page.goto(`${HUELLE}/?k=region&quellen=europe/dach,europe/italy`);
	await expect(page.getByText('merged-19b731a7.osm.pbf')).toBeVisible();
}

test('erweitern übernimmt die geladenen Bestandteile und fügt hinzu', async ({ page }) => {
	await oeffnen(page);
	await page.getByRole('button', { name: 'Region erweitern' }).click();

	await expect(marken(page)).toHaveText([/^europe\/dach/, /^europe\/italy/]);

	await page.getByPlaceholder(/Region suchen/).fill('pol');
	await page.getByRole('button', { name: 'Europe › Poland' }).click();
	await page.getByRole('button', { name: 'Bayern' }).click();
	await expect(marken(page)).toHaveCount(4);

	await page.getByRole('button', { name: 'Wechsel starten' }).click();
	await expect.poll(() => page.evaluate(() => window.__regionWechsel)).toEqual([
		geo('europe/dach'),
		geo('europe/italy'),
		geo('europe/poland'),
		geo('europe/germany/bayern'),
	]);
});

test('ein übernommener Bestandteil lässt sich entfernen', async ({ page }) => {
	await oeffnen(page);
	await page.getByRole('button', { name: 'Region erweitern' }).click();

	await page.getByRole('button', { name: 'europe/italy entfernen' }).click();
	await expect(marken(page)).toHaveText([/^europe\/dach/]);
});

test('Region wechseln beginnt weiter leer', async ({ page }) => {
	await oeffnen(page);
	await page.getByRole('button', { name: 'Region wechseln' }).click();

	await expect(marken(page)).toHaveCount(0);
	await page.getByRole('button', { name: 'Bayern' }).click();
	await page.getByRole('button', { name: 'Wechsel starten' }).click();
	await expect.poll(() => page.evaluate(() => window.__regionWechsel)).toEqual([geo('europe/germany/bayern')]);
});
