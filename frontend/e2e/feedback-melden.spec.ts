import { expect, test, type Page } from '@playwright/test';
import { blockExternal } from './fixtures';

/**
 * Der Melde-Dialog — was er abschickt und was nicht.
 *
 * Die Zusage, die hier geprüft wird, sieht man einem Bildschirmfoto der
 * Oberfläche nicht an: **mitgeschickt wird genau das, was der Ausklapper
 * „Was mitgeschickt wird" nennt** — nicht mehr. Eine Meldefunktion, die
 * nebenher noch etwas anderes aus dem Browser mitnimmt, wäre auf einer
 * BOS-Instanz ein echtes Problem, und sie würde still entstehen: ein Feld
 * mehr im `submit`-Aufruf fällt niemandem auf.
 *
 * Gemountet wird die Komponente in der Hülle (`e2e/harness/`, `?k=feedback`)
 * mit gestubbter `$lib/api`; abgelegt wird die Nutzlast unter
 * `window.__letzteMeldung`.
 */

const HUELLE = 'http://localhost:4174/?k=feedback';

/** Ein gültiges 1×1-PNG — muss ein echtes Bild sein, der Dialog lädt es. */
const PNG_1x1 = Buffer.from(
	'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
	'base64',
);

async function meldungAusfuellen(page: Page, titel: string, text: string) {
	await page.getByRole('textbox').first().fill(titel);
	await page.locator('textarea').fill(text);
}

function nutzlast(page: Page) {
	return page.evaluate(() => (window as unknown as { __letzteMeldung?: Record<string, unknown> }).__letzteMeldung);
}

function anzahlMeldungen(page: Page) {
	return page.evaluate(() => (window as unknown as { __meldungen?: number }).__meldungen ?? 0);
}

test.beforeEach(async ({ page }) => {
	await blockExternal(page);
	await page.goto(HUELLE);
	await expect(page.getByRole('dialog')).toBeVisible();
});

test('mitgeschickt wird genau das, was der Ausklapper nennt', async ({ page }) => {
	await page.getByText('Was mitgeschickt wird').click();
	const genannt = await page.locator('.umgebung dt').allTextContents();
	// Die letzte Zeile beschreibt das Konto in Worten; die Felder davor sind
	// die Schlüssel, die tatsächlich im Aufruf stehen.
	const genannteFelder = genannt.filter((t) => t !== 'Konto');
	expect(genannteFelder).toEqual(['page_url', 'user_agent', 'app_version', 'viewport']);

	await meldungAusfuellen(page, 'Route rechnet nicht neu', 'Nach dem Speichern bleibt die alte Route stehen.');
	await page.getByRole('button', { name: 'Absenden' }).click();
	await expect(page.getByText('Die Meldung ist angekommen.')).toBeVisible();

	const daten = await nutzlast(page);
	expect(daten).toBeTruthy();
	// Inhalt der Meldung + genau die genannten Umgebungsfelder. Kein Feld mehr:
	// keine Cookies, keine Kennungen, nichts aus dem `localStorage`.
	expect(Object.keys(daten!).sort()).toEqual(
		['app_version', 'description', 'kind', 'page_url', 'screenshot', 'severity', 'title', 'user_agent', 'viewport'],
	);
	expect(daten!.kind).toBe('bug');
	expect(daten!.screenshot).toBeNull();
	expect(daten!.page_url).toContain('/?k=feedback');
});

test('eine unvollständige Meldung geht gar nicht erst hinaus', async ({ page }) => {
	await meldungAusfuellen(page, 'Ok', 'zu kurz');
	await page.getByRole('button', { name: 'Absenden' }).click();

	await expect(page.getByText('Bitte eine kurze Überschrift angeben.')).toBeVisible();
	expect(await anzahlMeldungen(page)).toBe(0);
});

test('das Bildschirmfoto geht nur mit, wenn eines dranhängt', async ({ page }) => {
	await meldungAusfuellen(page, 'Karte bleibt grau', 'Beim Wechsel auf Satellit bleibt die Fläche leer.');

	await page.locator('input[type="file"]').setInputFiles({
		name: 'schirm.png',
		mimeType: 'image/png',
		buffer: PNG_1x1,
	});
	await expect(page.getByAltText('Aufgenommenes Bildschirmfoto')).toBeVisible();

	// Wieder entfernt — dann darf auch nichts davon im Aufruf stehen.
	await page.getByRole('button', { name: 'Entfernen' }).click();
	await expect(page.getByAltText('Aufgenommenes Bildschirmfoto')).toHaveCount(0);

	await page.getByRole('button', { name: 'Absenden' }).click();
	await expect(page.getByText('Die Meldung ist angekommen.')).toBeVisible();
	expect((await nutzlast(page))!.screenshot).toBeNull();
});

test('ein angehängtes Bildschirmfoto liegt als Bild in der Meldung', async ({ page }) => {
	await meldungAusfuellen(page, 'Karte bleibt grau', 'Beim Wechsel auf Satellit bleibt die Fläche leer.');
	await page.locator('input[type="file"]').setInputFiles({
		name: 'schirm.png',
		mimeType: 'image/png',
		buffer: PNG_1x1,
	});
	await expect(page.getByAltText('Aufgenommenes Bildschirmfoto')).toBeVisible();

	await page.getByRole('button', { name: 'Absenden' }).click();
	await expect(page.getByText('Die Meldung ist angekommen.')).toBeVisible();

	const bild = (await nutzlast(page))!.screenshot as string;
	// Data-URL eines Rasterformats — das Backend nimmt nichts anderes an.
	expect(bild).toMatch(/^data:image\/(png|jpeg|webp);base64,/);
});
