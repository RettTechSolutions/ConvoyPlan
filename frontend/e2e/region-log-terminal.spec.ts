import { test, expect, type Page } from '@playwright/test';

// Log-Terminal der Kartenregion (gilt ebenso für das Update-Log, dieselbe
// Mechanik aus `$lib/terminal`). Der Strom liest beim Verbinden ab Byte 0, ein
// abgeschlossener Wechsel schickt also bei jedem Öffnen der Seite sein ganzes
// Log noch einmal. Die Zusagen:
//  - das Terminal steht danach am Ende, und zwar ohne sichtbar von oben dorthin
//    zu spulen — gemeldet war genau das, bei jedem Seitenaufruf;
//  - wer hochgescrollt hat, bleibt dort, auch wenn neue Zeilen kommen;
//  - wer am Ende steht, folgt den neuen Zeilen.

const HUELLE = 'http://localhost:4174';
const terminal = (page: Page) => page.locator('.update-terminal');

/** Jede Scrollposition des Terminals mitschreiben, vom ersten Ereignis an. */
async function scrollMitschreiben(page: Page) {
	await page.addInitScript(() => {
		(window as unknown as { __scrolls: number[] }).__scrolls = [];
		document.addEventListener(
			'scroll',
			(e) => {
				const el = e.target as HTMLElement;
				if (el.classList?.contains('update-terminal')) {
					(window as unknown as { __scrolls: number[] }).__scrolls.push(el.scrollTop);
				}
			},
			{ capture: true },
		);
	});
}

/** Eine neue Zeile in den offenen Strom geben (Stub in `harness/api-stub.ts`). */
const zeile = (page: Page, text: string) =>
	page.evaluate(
		(t) => (window as unknown as { __regionLogZeile?: (z: string) => void }).__regionLogZeile?.(t),
		text,
	);

const amEnde = (page: Page) =>
	terminal(page).evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight <= 2);

test('ein abgeschlossener Wechsel steht beim Öffnen am Ende, ohne zu spulen', async ({ page }) => {
	await scrollMitschreiben(page);
	await page.goto(`${HUELLE}/?k=region&log=400&phase=done`);

	await expect(terminal(page)).toContainText('Regionswechsel abgeschlossen');
	await expect(terminal(page)).toContainText('─── Abgeschlossen ───');
	await expect.poll(() => amEnde(page)).toBe(true);

	// Keine Animation: Ein weicher Bildlauf liefe durch alle Zwischenstellungen.
	expect(await terminal(page).evaluate((el) => getComputedStyle(el).scrollBehavior)).not.toBe('smooth');
	const ende = await terminal(page).evaluate((el) => el.scrollTop);
	const scrolls = await page.evaluate(() => (window as unknown as { __scrolls: number[] }).__scrolls);
	expect(scrolls.length).toBeGreaterThan(0);
	// Höchstens die Schlusszeile („─── Abgeschlossen ───") darf nachrücken.
	expect(Math.min(...scrolls)).toBeGreaterThan(ende - 60);
});

test('wer hochgescrollt hat, bleibt dort; wer am Ende steht, folgt', async ({ page }) => {
	await page.goto(`${HUELLE}/?k=region&log=200&phase=importing`);
	await expect(terminal(page)).toContainText('Regionswechsel abgeschlossen');
	await expect.poll(() => amEnde(page)).toBe(true);

	await terminal(page).evaluate((el) => {
		el.scrollTop = 0;
	});
	await zeile(page, 'neue Zeile beim Lesen');
	await expect(terminal(page)).toContainText('neue Zeile beim Lesen');
	// Zwei Bildaufbauten abwarten, in denen ein Sprung ans Ende passiert wäre.
	await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
	expect(await terminal(page).evaluate((el) => el.scrollTop)).toBe(0);

	await terminal(page).evaluate((el) => {
		el.scrollTop = el.scrollHeight;
	});
	await zeile(page, 'neue Zeile am Ende');
	await expect(terminal(page)).toContainText('neue Zeile am Ende');
	await expect.poll(() => amEnde(page)).toBe(true);
});

// „Schließen" gilt am Server, nicht nur für den Seitenaufruf: Vorher klappte
// jedes Öffnen des Admin-Portals denselben Endstatus samt Log wieder auf, bis
// zum nächsten Wechsel.
test('ein geschlossener Wechsel bleibt nach dem Neuladen zu', async ({ page }) => {
	await page.goto(`${HUELLE}/?k=region&log=50&phase=done`);
	await expect(terminal(page)).toContainText('─── Abgeschlossen ───');

	await page.getByRole('button', { name: 'Schließen' }).click();
	await expect(terminal(page)).toHaveCount(0);

	await page.reload();
	await expect(page.getByText('dach-latest.osm.pbf')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Region wechseln' })).toBeVisible();
	await expect(terminal(page)).toHaveCount(0);
});
