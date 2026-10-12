import { test, expect, type Locator, type Page } from '@playwright/test';
import { blockExternal, konvoiFahrzeug, mockOrgPortal, position } from './fixtures';

// Das Kontextmenü (rechte Maustaste, Tastatur, langes Drücken). Zusagen, die
// man einem Bildschirmfoto nicht ansieht:
//
// - Wo der Browser sein eigenes Menü braucht — Eingabefeld, Link, markierter
//   Text, Umschalt gedrückt —, bleibt es seins. Sonst ginge „Einfügen" verloren.
// - Ein Menü ohne einzige Aktion geht gar nicht erst auf.
// - Bedienbar ohne Maus: Pfeiltasten überspringen Gesperrtes, Esc gibt den
//   Fokus dorthin zurück, wo er war.
// - Es bleibt im Fenster, auch ganz unten rechts.
// - Am Telefon öffnet langes Drücken es, und der Klick danach löst die Zeile
//   nicht zusätzlich aus.
// - In der echten App hängt es im Wurzel-Layout: die Fahrzeugliste der
//   Konvoi-Ansicht bekommt eines.

const HUELLE = 'http://localhost:4174/?k=kontextmenue';
const menue = (page: Page) => page.getByRole('menu');

/** Ob das letzte `contextmenu` dem Browser gelassen wurde. */
async function browsermenueBlieb(page: Page): Promise<boolean> {
	return page.evaluate(() => !(window as unknown as { __letztesKm: boolean }).__letztesKm);
}

/**
 * Ein `contextmenu`, wie der Browser es schickt — als `MouseEvent`.
 * Playwrights `dispatchEvent` baut dafür nur ein schlichtes `Event` ohne
 * Koordinaten. (0, 0) ist das, was die Tastatur auslöst.
 */
async function kontext(ziel: Locator, x = 0, y = 0) {
	await ziel.evaluate((el, [x, y]) => {
		el.dispatchEvent(new MouseEvent('contextmenu', { clientX: x, clientY: y, button: 2, bubbles: true, cancelable: true }));
	}, [x, y]);
}

async function huelle(page: Page) {
	await page.goto(HUELLE);
	await page.evaluate(() => {
		window.addEventListener('contextmenu', (e) => {
			(window as unknown as { __letztesKm: boolean }).__letztesKm = e.defaultPrevented;
		});
	});
}

test('Rechtsklick öffnet das Menü, eine Aktion läuft und schließt es', async ({ page }) => {
	await huelle(page);
	await page.getByTestId('punkt-1').click({ button: 'right', position: { x: 10, y: 8 } });
	await expect(menue(page)).toBeVisible();
	expect(await browsermenueBlieb(page)).toBe(false);

	// Aufgeräumt: kein Trenner am Anfang, am Ende oder doppelt.
	const kinder = menue(page).locator(':scope > *');
	await expect(kinder.first()).toHaveText('Rastplatz Irschenberg');
	await expect(kinder.last()).toContainText('Löschen');
	await expect(menue(page).locator('.trenner + .trenner')).toHaveCount(0);

	await menue(page).getByRole('menuitem', { name: 'Nach oben' }).click();
	await expect(menue(page)).toHaveCount(0);
	await expect(page.getByTestId('punkt-0')).toContainText('Rastplatz Irschenberg');
	// Der Rechtsklick ist kein Klick auf die Zeile.
	await expect(page.locator('.klicks')).toHaveText('Zeilenklicks: 0');
});

test('Gesperrte Einträge sagen warum und tun nichts', async ({ page }) => {
	await huelle(page);
	await page.getByTestId('punkt-0').click({ button: 'right', position: { x: 10, y: 8 } });
	const gesperrt = menue(page).getByRole('menuitem', { name: 'Gesperrt' });
	await expect(gesperrt).toBeDisabled();
	await expect(gesperrt).toHaveAttribute('title', 'Geht hier nicht');
	// Erster Punkt: nach oben geht nicht, an den Anfang steht gar nicht da.
	await expect(menue(page).getByRole('menuitem', { name: 'Nach oben' })).toBeDisabled();
	await expect(menue(page).getByRole('menuitem', { name: 'An den Anfang' })).toHaveCount(0);
	await gesperrt.click({ force: true });
	await expect(page.locator('.geloescht')).toHaveText('Gelöscht: –');
});

test('Eingabefeld, Link, markierter Text und Umschalt behalten das Browsermenü', async ({ page }) => {
	await huelle(page);
	const zeile = page.getByTestId('punkt-0');

	await zeile.getByRole('textbox').click({ button: 'right' });
	await expect(menue(page)).toHaveCount(0);
	expect(await browsermenueBlieb(page)).toBe(true);

	await zeile.getByRole('link').click({ button: 'right' });
	await expect(menue(page)).toHaveCount(0);
	expect(await browsermenueBlieb(page)).toBe(true);

	await page.keyboard.down('Shift');
	await zeile.click({ button: 'right', position: { x: 10, y: 8 } });
	await page.keyboard.up('Shift');
	await expect(menue(page)).toHaveCount(0);
	expect(await browsermenueBlieb(page)).toBe(true);

	// Text markiert: Kopieren ist dann das, was man will.
	await page.evaluate(() => {
		const li = document.querySelector('[data-testid="punkt-0"]')!;
		const r = document.createRange();
		r.selectNodeContents(li.firstChild!);
		getSelection()!.removeAllRanges();
		getSelection()!.addRange(r);
	});
	await kontext(zeile, 20, 20);
	await expect(menue(page)).toHaveCount(0);
	expect(await browsermenueBlieb(page)).toBe(true);
});

test('Ohne Aktion bleibt das Menü zu', async ({ page }) => {
	await huelle(page);
	await page.locator('.ohne').click({ button: 'right' });
	await expect(menue(page)).toHaveCount(0);
	expect(await browsermenueBlieb(page)).toBe(true);
});

test('Ohne Maus: Pfeiltasten, gesperrte überspringen, Esc gibt den Fokus zurück', async ({ page }) => {
	await huelle(page);
	const zeile = page.getByTestId('punkt-1');
	await zeile.focus();
	// Taste „Kontextmenü"/Umschalt+F10: der Browser meldet es ohne Zeigerposition.
	await kontext(zeile, 0, 0);
	await expect(menue(page)).toBeVisible();

	// Das Menü steht unter der Zeile, nicht in der Ecke oben links.
	const z = (await zeile.boundingBox())!;
	const m = (await menue(page).boundingBox())!;
	expect(m.y).toBeGreaterThanOrEqual(z.y + z.height - 1);

	await expect(menue(page).getByRole('menuitem', { name: 'Nach oben' })).toBeFocused();
	await page.keyboard.press('End');
	await expect(menue(page).getByRole('menuitem', { name: 'Löschen' })).toBeFocused();
	// „Gesperrt" liegt dazwischen und wird übersprungen.
	await page.keyboard.press('ArrowUp');
	await expect(menue(page).getByRole('menuitem', { name: 'Namen kopieren' })).toBeFocused();
	// Anfangsbuchstabe springt.
	await page.keyboard.press('a');
	await expect(menue(page).getByRole('menuitem', { name: 'An den Anfang' })).toBeFocused();

	await page.keyboard.press('Escape');
	await expect(menue(page)).toHaveCount(0);
	await expect(zeile).toBeFocused();

	// Und per Enter ausgeführt.
	await kontext(zeile, 0, 0);
	await page.keyboard.press('End');
	await page.keyboard.press('Enter');
	await expect(page.locator('.geloescht')).toHaveText('Gelöscht: Rastplatz Irschenberg');
});

test('Klick daneben schließt, ohne etwas auszulösen', async ({ page }) => {
	await huelle(page);
	await page.getByTestId('punkt-0').click({ button: 'right', position: { x: 10, y: 8 } });
	await expect(menue(page)).toBeVisible();
	await page.locator('.geloescht').click();
	await expect(menue(page)).toHaveCount(0);
	await expect(page.locator('.geloescht')).toHaveText('Gelöscht: –');
});

test('Ganz unten rechts bleibt das Menü im Fenster', async ({ page }) => {
	await page.setViewportSize({ width: 420, height: 300 });
	await huelle(page);
	const zeile = page.getByTestId('punkt-2');
	await kontext(zeile, 415, 295);
	await expect(menue(page)).toBeVisible();
	const m = (await menue(page).boundingBox())!;
	expect(m.x).toBeGreaterThanOrEqual(0);
	expect(m.y).toBeGreaterThanOrEqual(0);
	expect(m.x + m.width).toBeLessThanOrEqual(420);
	expect(m.y + m.height).toBeLessThanOrEqual(300);
});

test('Kopieren landet in der Zwischenablage und sagt es', async ({ page, context }) => {
	await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'http://localhost:4174' });
	await huelle(page);
	await page.getByTestId('punkt-2').click({ button: 'right', position: { x: 10, y: 8 } });
	await menue(page).getByRole('menuitem', { name: 'Namen kopieren' }).click();
	await expect(page.getByRole('status')).toHaveText('In die Zwischenablage kopiert');
	expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('Ziel');
});

test('Langes Drücken öffnet es am Telefon, der Klick danach zählt nicht', async ({ page }) => {
	await huelle(page);
	const zeile = page.getByTestId('punkt-0');
	const b = (await zeile.boundingBox())!;
	const bei = { clientX: b.x + 10, clientY: b.y + 8, pointerType: 'touch', isPrimary: true, bubbles: true };
	await zeile.dispatchEvent('pointerdown', bei);
	await page.waitForTimeout(250);
	// Noch zu kurz.
	await expect(menue(page)).toHaveCount(0);
	await expect(menue(page)).toBeVisible({ timeout: 2000 });
	await zeile.dispatchEvent('pointerup', bei);
	await zeile.dispatchEvent('click', { bubbles: true, cancelable: true });
	await expect(page.locator('.klicks')).toHaveText('Zeilenklicks: 0');
	// Android schickt danach noch sein eigenes contextmenu: kein zweites Menü, kein Browsermenü.
	await kontext(zeile, bei.clientX, bei.clientY);
	expect(await browsermenueBlieb(page)).toBe(false);
	await expect(menue(page)).toHaveCount(1);
});

test('Wischen ist kein langes Drücken', async ({ page }) => {
	await huelle(page);
	const zeile = page.getByTestId('punkt-0');
	const b = (await zeile.boundingBox())!;
	await zeile.dispatchEvent('pointerdown', { clientX: b.x + 10, clientY: b.y + 8, pointerType: 'touch', bubbles: true });
	await zeile.dispatchEvent('pointermove', { clientX: b.x + 40, clientY: b.y + 8, pointerType: 'touch', bubbles: true });
	await page.waitForTimeout(700);
	await expect(menue(page)).toHaveCount(0);
});

// ── In der echten App ──────────────────────────────────────────────────

const SLUG = 'km-org';
const CONVOY = 'c-km';

test('Konvoi-Ansicht: Fahrzeugzeile hat ein Menü, „Auf Karte zeigen" nur mit Position', async ({ page }) => {
	await blockExternal(page);
	await page.routeWebSocket(/\/api\/ws\//, () => {});
	await mockOrgPortal(page, {
		slug: SLUG, convoyId: CONVOY,
		fahrzeuge: [
			konvoiFahrzeug({ position: 1, vehicle: { id: 'v-hlf', name: 'HLF 20', callsign: 'Florian 1/46' } }),
			konvoiFahrzeug({ position: 2, vehicle: { id: 'v-mtw', name: 'MTW', callsign: null } }),
		],
		positionen: [position('v-hlf')],
	});
	await page.goto(`/o/${SLUG}/tracking/${CONVOY}`, { waitUntil: 'domcontentloaded' });

	const hlf = page.locator('.vehicle-row', { hasText: 'HLF 20' });
	await hlf.click({ button: 'right' });
	await expect(menue(page)).toBeVisible();
	await expect(menue(page)).toContainText('HLF 20 · Florian 1/46');
	await expect(menue(page).getByRole('menuitem', { name: 'Auf Karte zeigen' })).toBeEnabled();
	await expect(menue(page).getByRole('menuitem', { name: 'Funkrufname kopieren' })).toBeVisible();
	await page.keyboard.press('Escape');

	const mtw = page.locator('.vehicle-row', { hasText: 'MTW' });
	await mtw.click({ button: 'right' });
	const zeigen = menue(page).getByRole('menuitem', { name: 'Auf Karte zeigen' });
	await expect(zeigen).toBeDisabled();
	await expect(zeigen).toHaveAttribute('title', 'Keine Position gemeldet');
	// Ohne Funkrufnamen gibt es nichts zu kopieren — und keinen Eintrag dafür.
	await expect(menue(page).getByRole('menuitem', { name: 'Funkrufname kopieren' })).toHaveCount(0);
});
