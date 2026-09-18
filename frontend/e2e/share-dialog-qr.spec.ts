import { test, expect } from '@playwright/test';
import { printAufrufe, stubPrint } from './fixtures';

/**
 * Der Teilen-Dialog in der Komponentenhülle (`e2e/harness/`) — mit gestubbter
 * `$lib/api`, weil er in der App hinter der Anmeldung sitzt.
 */
const HUELLE = 'http://localhost:4174/';
const PASSWORT = 'Xh4Kq7Tp2M';

test.beforeEach(async ({ page }) => {
	await stubPrint(page);
	await page.goto(HUELLE);
	await expect(page.getByRole('heading', { name: 'Live-Tracking teilen' })).toBeVisible();
});

test('nur aktive Links haben einen QR-Knopf', async ({ page }) => {
	await expect(page.getByTitle('QR-Code anzeigen')).toHaveCount(2);

	const widerrufen = page.getByRole('row').filter({ hasText: 'GLhXPSX0' });
	await expect(widerrufen).toContainText('widerrufen');
	await expect(widerrufen.getByTitle('QR-Code anzeigen')).toHaveCount(0);
});

test('das QR-Fenster zeigt Code und Adresse und schließt allein', async ({ page }) => {
	await page.getByTitle('QR-Code anzeigen').first().click();

	const fenster = page.getByRole('dialog').filter({ hasText: 'QR-Code · 6dA4KrUG' });
	await expect(fenster.locator('.qs img')).toBeVisible();
	await expect(fenster.locator('input[readonly]')).toHaveValue(
		'https://demo.convoyplan.de/track/6dA4KrUG',
	);

	// Esc nimmt das QR-Fenster weg, nicht den Dialog darunter.
	await page.keyboard.press('Escape');
	await expect(page.getByRole('heading', { name: /QR-Code · / })).toHaveCount(0);
	await expect(page.getByRole('heading', { name: 'Live-Tracking teilen' })).toBeVisible();
});

test('ein geschützter Link sagt, dass das Passwort hier nicht zu holen ist', async ({ page }) => {
	await page.getByRole('row').filter({ hasText: 'pENCIVTf' }).getByTitle('QR-Code anzeigen').click();
	await expect(page.getByText(/lässt sich\s+nicht erneut abrufen/)).toBeVisible();
});

test('der Download heißt nach dem Slug', async ({ page }) => {
	await page.getByTitle('QR-Code anzeigen').first().click();
	const [download] = await Promise.all([
		page.waitForEvent('download'),
		page.getByRole('button', { name: 'PNG herunterladen' }).click(),
	]);
	expect(download.suggestedFilename()).toBe('tracking-6dA4KrUG.png');
});

test('der frisch erstellte Link bringt Code, PNG und Ausdruck gleich mit', async ({ page }) => {
	await page.getByRole('button', { name: 'Link erstellen' }).click();

	const block = page.locator('.sl-result');
	await expect(block.locator('.qs img')).toBeVisible();
	// Das Passwort steht in einem Feld zum Kopieren, nicht im Fließtext.
	await expect(block.locator('.sl-pw')).toHaveValue(PASSWORT);

	const [download] = await Promise.all([
		page.waitForEvent('download'),
		block.getByRole('button', { name: 'PNG herunterladen' }).click(),
	]);
	expect(download.suggestedFilename()).toBe('tracking-Nw7Kq2Zt.png');

	await block.getByRole('button', { name: 'Drucken' }).click();
	expect(await printAufrufe(page)).toBe(1);

	// Der Dialog zeigt das Passwort genau hier — der Ausdruck nie.
	const blatt = page.locator('body > .cp-print-sheet');
	await expect(blatt).toContainText('track/Nw7Kq2Zt');
	await expect(blatt).not.toContainText(PASSWORT);
});

test('der Ausdruck nimmt die Seite darunter nicht mit', async ({ page }) => {
	await page.getByTitle('QR-Code anzeigen').first().click();
	await page.getByRole('button', { name: 'Drucken' }).click();
	await page.emulateMedia({ media: 'print' });

	const fuellerSichtbar = await page.evaluate(
		() => getComputedStyle(document.querySelector('.filler')!).display,
	);
	expect(fuellerSichtbar).toBe('none');
	await expect(page.locator('body > .cp-print-sheet')).toBeVisible();
});
