import { test, expect, type Page, type Locator } from '@playwright/test';
import { blockExternal, mockTrack } from './fixtures';

/**
 * Zwei Zusagen, die man einem Bildschirmfoto nicht ansieht und die trotzdem
 * still falsch werden können:
 *
 * 1. **Ein Dialog ragt nie aus dem sichtbaren Bereich.** Tat er es, standen
 *    *Speichern* und *Abbrechen* unterhalb des Randes — und mit *Abbrechen*
 *    der einzige sichtbare Weg heraus. Auf dem Telefon kam das durch `90vh`
 *    zustande: iOS Safari misst `vh` gegen die Anzeigefläche mit eingefahrener
 *    Adressleiste, der Dialog endete also hinter der Leiste.
 * 2. **Kein Eingabefeld ist auf einem Telefon kleiner als 16px.** Darunter
 *    zoomt iOS Safari beim Antippen in die Seite hinein und kommt nicht von
 *    selbst zurück; zurückschieben lässt sie sich wegen `overflow-x: clip`
 *    auch nicht. Die Seite bleibt verschoben stehen.
 */

const HUELLE = 'http://localhost:4174';

/** Liegt das Element vollständig im sichtbaren Bereich? */
async function imSchirm(page: Page, ziel: Locator) {
	const kasten = await ziel.boundingBox();
	const schirm = page.viewportSize()!;
	if (!kasten) throw new Error('Element hat keinen Kasten');
	return {
		...kasten,
		passt:
			kasten.y >= -0.5 &&
			kasten.x >= -0.5 &&
			kasten.y + kasten.height <= schirm.height + 0.5 &&
			kasten.x + kasten.width <= schirm.width + 0.5,
	};
}

test.describe('Marschverband-Dialog', () => {
	// Niedrig genug, dass die neun Felder nicht hineinpassen — genau der Fall,
	// in dem die Knöpfe vorher unterhalb des Randes lagen.
	test.use({ viewport: { width: 390, height: 600 } });

	test.beforeEach(async ({ page }) => {
		await blockExternal(page);
		await page.goto(`${HUELLE}/?k=konvoi`);
		await expect(page.getByRole('dialog')).toBeVisible();
	});

	test('bleibt im sichtbaren Bereich, nur die Felder scrollen', async ({ page }) => {
		const dialog = page.getByRole('dialog');
		expect((await imSchirm(page, dialog)).passt).toBe(true);

		// Der Rumpf ist der einzige Teil, der scrollt — daran erkennt man, dass
		// der Dialog seine Höhe begrenzt und nicht einfach hinausragt.
		const rumpf = dialog.locator('div').filter({ has: page.getByLabel('Name *') }).last();
		const scrollt = await rumpf.evaluate((el) => el.scrollHeight > el.clientHeight + 1);
		expect(scrollt).toBe(true);
	});

	test('Speichern und Abbrechen stehen ohne Scrollen bereit', async ({ page }) => {
		for (const name of ['Speichern', 'Abbrechen', 'Löschen']) {
			const knopf = page.getByRole('button', { name });
			await expect(knopf).toBeVisible();
			expect((await imSchirm(page, knopf)).passt, `${name} liegt außerhalb`).toBe(true);
		}
	});

	test('bleibt beim Scrollen in den Feldern stehen', async ({ page }) => {
		const dialog = page.getByRole('dialog');
		const vorher = await imSchirm(page, dialog);

		await page.getByLabel('Fahrzeugabstand Autobahn (m)').scrollIntoViewIfNeeded();

		const nachher = await imSchirm(page, dialog);
		expect(nachher.passt).toBe(true);
		expect(Math.round(nachher.y)).toBe(Math.round(vorher.y));
		// Das letzte Feld ist jetzt erreichbar, der Fuß steht weiterhin darunter.
		expect((await imSchirm(page, page.getByLabel('Fahrzeugabstand Autobahn (m)'))).passt).toBe(true);
		expect((await imSchirm(page, page.getByRole('button', { name: 'Speichern' }))).passt).toBe(true);
	});

	test('Escape schließt ihn — auch ohne einen Knopf zu treffen', async ({ page }) => {
		await page.keyboard.press('Escape');
		await expect(page.getByRole('dialog')).toHaveCount(0);
	});
});

test.describe('Eingabefelder auf dem Telefon', () => {
	// `hasTouch` schaltet in Chromium `(pointer: coarse)` ein — die Bedingung,
	// unter der die Untergrenze in `app.html` greift.
	test.use({ viewport: { width: 390, height: 664 }, hasTouch: true, isMobile: true });

	/**
	 * Die Fahreransicht, weil dort die kleinsten Felder der App stehen
	 * (`--text-sm` = 13px): Statusauswahl und Notizfeld. Sie sind zugleich die,
	 * die im Einsatz am häufigsten angetippt werden.
	 */
	test('sind nie kleiner als 16px, damit iOS nicht hineinzoomt', async ({ page }) => {
		await blockExternal(page);
		await mockTrack(page, { scope: 'driver' });
		await page.goto('/track/6dA4KrUG', { waitUntil: 'domcontentloaded' });
		await expect(page.getByRole('combobox').first()).toBeVisible();

		expect(await page.evaluate(() => matchMedia('(pointer: coarse)').matches)).toBe(true);

		const felder = await page.evaluate(() =>
			[...document.querySelectorAll('input, select, textarea')]
				.filter((el) => (el as HTMLElement).offsetParent !== null)
				.map((el) => ({
					feld: el.id || el.getAttribute('name') || el.className || el.tagName,
					px: parseFloat(getComputedStyle(el).fontSize),
				})),
		);

		// Ohne diese Zusicherung wäre der Test auch dann grün, wenn die Ansicht
		// gar keine Felder mehr zeigte.
		expect(felder.length).toBeGreaterThan(0);
		expect(felder.filter((f) => f.px < 16)).toEqual([]);
	});
});
