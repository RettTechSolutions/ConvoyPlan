import { test, expect, type Page } from '@playwright/test';
import { createRequire } from 'node:module';
import { blockExternal, mockTrack, printAufrufe, qrInhalt, stubPrint } from './fixtures';

const require = createRequire(import.meta.url);
const JSQR = require.resolve('jsqr/dist/jsQR.js');

const SLUG = '6dA4KrUG';
const QR_BILD = '.qs img';

async function oeffnen(page: Page, scope: 'track' | 'driver') {
	await stubPrint(page);
	await blockExternal(page);
	await mockTrack(page, { scope });
	await page.goto(`/track/${SLUG}`, { waitUntil: 'domcontentloaded' });
	await page.getByRole('button', { name: /Link (weitergeben|für Mitfahrer)/ }).click();
	await expect(page.locator(QR_BILD)).toBeVisible();
}

test.describe('Tracking-Ansicht: Link weitergeben', () => {
	test('Viewer sieht den sachlichen Hinweis, Fahrer die Warnung', async ({ page }) => {
		await oeffnen(page, 'track');
		await expect(page.getByRole('button', { name: /Link weitergeben \(QR\)/ })).toBeVisible();
		await expect(page.getByText(/sieht denselben Verband live/)).toBeVisible();
		await expect(page.getByText(/Position\s+und Status senden\./)).toHaveCount(0);

		await page.goto('about:blank');
		await oeffnen(page, 'driver');
		await expect(page.getByRole('button', { name: /Link für Mitfahrer \(QR\)/ })).toBeVisible();
		await expect(page.getByText(/kann ebenfalls ein\s+Fahrzeug wählen/)).toBeVisible();
	});

	test('der Code trägt die Tracking-Adresse — ohne Query, Fragment oder Token', async ({ page }) => {
		await oeffnen(page, 'driver');
		await page.addScriptTag({ path: JSQR });

		const inhalt = await qrInhalt(page, QR_BILD);
		expect(inhalt).toBe(`http://localhost:4173/track/${SLUG}`);
		// Das Sitzungstoken lebt im sessionStorage und hat im weitergereichten
		// Bild nichts zu suchen — ebenso wenig irgendein Anhängsel.
		expect(inhalt).not.toContain('token');
		expect(inhalt).not.toContain('?');
		expect(inhalt).not.toContain('#');
	});

	test('der Download heißt nach dem Slug', async ({ page }) => {
		await oeffnen(page, 'driver');
		const [download] = await Promise.all([
			page.waitForEvent('download'),
			page.getByRole('button', { name: 'PNG herunterladen' }).click(),
		]);
		expect(download.suggestedFilename()).toBe(`tracking-${SLUG}.png`);
	});

	test('bei einem geschützten Link steht der Passworthinweis — das Passwort nirgends', async ({ page }) => {
		await stubPrint(page);
		await blockExternal(page);
		await mockTrack(page, { scope: 'driver', password: 'Marschbefehl42' });
		await page.goto(`/track/${SLUG}`, { waitUntil: 'domcontentloaded' });

		await page.getByPlaceholder('Passwort').fill('Marschbefehl42');
		await page.getByRole('button', { name: 'Öffnen' }).click();
		await page.getByRole('button', { name: /Link für Mitfahrer/ }).click();
		await expect(page.locator(QR_BILD)).toBeVisible();

		await expect(page.getByText(/Zusätzlich wird das Passwort gebraucht/)).toBeVisible();

		await page.getByRole('button', { name: 'Drucken' }).click();
		const blatt = page.locator('body > .cp-print-sheet');
		await expect(blatt).toHaveCount(1);
		await expect(blatt).toContainText('passwortgeschützt');
		await expect(blatt).not.toContainText('Marschbefehl42');
		await expect(blatt).not.toContainText('test-sitzungstoken');
	});

	test('der Ausdruck steht allein auf dem Blatt', async ({ page }) => {
		await oeffnen(page, 'driver');
		await page.getByRole('button', { name: 'Drucken' }).click();
		expect(await printAufrufe(page)).toBe(1);

		await page.emulateMedia({ media: 'print' });

		// Alles außer dem Blatt ist im Druck weg — nicht bloß unsichtbar, sonst
		// bliebe das Layout stehen und hinge als leere Folgeseiten hinterher.
		const uebrige = await page.evaluate(() =>
			[...document.body.children]
				.filter((el) => !el.classList.contains('cp-print-sheet'))
				.map((el) => getComputedStyle(el).display),
		);
		expect(uebrige.length).toBeGreaterThan(0);
		expect(uebrige.every((d) => d === 'none')).toBe(true);

		const blatt = page.locator('body > .cp-print-sheet');
		await expect(blatt).toBeVisible();
		await expect(blatt).toContainText('Verlegung Nord — Live-Tracking');
		await expect(blatt).toContainText(`/track/${SLUG}`);

		// Das dunkle Design sitzt auf `html`; sonst druckt es sich als schwarze
		// Fläche mit, sobald jemand Hintergrundgrafiken einschaltet.
		const hintergruende = await page.evaluate(() => [
			getComputedStyle(document.documentElement).backgroundColor,
			getComputedStyle(document.body).backgroundColor,
		]);
		expect(hintergruende).toEqual(['rgb(255, 255, 255)', 'rgb(255, 255, 255)']);

		// Und nach dem Druck räumt die Ansicht das Blatt wieder weg.
		await page.emulateMedia({ media: 'screen' });
		await page.evaluate(() => window.dispatchEvent(new Event('afterprint')));
		await expect(page.locator('.cp-print-sheet')).toHaveCount(0);
	});
});
