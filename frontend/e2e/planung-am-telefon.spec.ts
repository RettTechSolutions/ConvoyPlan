import { test, expect, type Page } from '@playwright/test';
import { planung, tab } from './kontextmenue-attrappe';

// Planung am Telefon. Die Seitenleiste ist dort eine Schublade über der Karte,
// und ihre Höhe ist knapp. Zusagen, die man einem Bildschirmfoto nur halb
// ansieht:
//
// - **Die Reiter stehen oben.** Der Kopf der Schublade trägt nur Logo und zwei
//   Knöpfe; am Telefon ist er klein, den Verbandsnamen zeigt die Kopfleiste.
// - **Im Reiter Fahrzeuge steht die Marschfolge offen**, Fahrzeugpool und
//   Sollstärke sind zugeklappt — der Pool nur, wenn der Verband schon Fahrzeuge
//   hat, sonst gäbe es nichts zu tun.
// - **„+ Neu" klappt den Pool auf**, denn sein Formular erscheint darin.
// - **Die Sollstärke-Felder tragen die Farben der Leiste**, nicht Browserweiß.

const TELEFON = { width: 390, height: 844 };
test.use({ viewport: TELEFON, hasTouch: true });

async function schublade(page: Page) {
	await planung(page);
	await page.getByRole('button', { name: 'Menü', exact: true }).click();
	await expect(page.locator('#sidebar')).toHaveClass(/open/);
}

const titel = (page: Page, name: RegExp) => page.getByRole('button', { name });

test('die Reiter stehen oben in der Schublade, nicht unter einem großen Logo', async ({ page }) => {
	await schublade(page);
	const reiter = tab(page, 'Wegpunkte');
	const box = (await reiter.boundingBox())!;
	// Mit dem großen Logo stand die Reiterzeile bei 243 px, kompakt bei 193 px.
	expect(box.y).toBeLessThan(220);
});

test('Fahrzeuge: Marschfolge offen, Pool und Sollstärke zu', async ({ page }) => {
	await schublade(page);
	await tab(page, 'Fahrzeuge').click();

	await expect(titel(page, /^Im Verband/)).toHaveAttribute('aria-expanded', 'true');
	await expect(titel(page, /^Meine Fahrzeuge \(3\)$/)).toHaveAttribute('aria-expanded', 'false');
	await expect(titel(page, /^Sollstärke/)).toHaveAttribute('aria-expanded', 'false');
	await expect(page.getByRole('spinbutton', { name: /^Führer / }).first()).toBeHidden();

	await titel(page, /^Sollstärke/).tap();
	const feld = page.getByRole('spinbutton', { name: /^Führer / }).first();
	await expect(feld).toBeVisible();
	const farbe = await feld.evaluate((el) => getComputedStyle(el).backgroundColor);
	expect(farbe).not.toBe('rgb(255, 255, 255)');
});

test('„+ Neu" klappt den Fahrzeugpool auf, damit das Formular zu sehen ist', async ({ page }) => {
	await schublade(page);
	await tab(page, 'Fahrzeuge').click();
	const pool = titel(page, /^Meine Fahrzeuge/);
	await expect(pool).toHaveAttribute('aria-expanded', 'false');

	const karte = page.locator('.section', { has: pool });
	await karte.getByRole('button', { name: '+ Neu' }).click();
	await expect(pool).toHaveAttribute('aria-expanded', 'true');
	await expect(page.getByPlaceholder('Name *')).toBeVisible();

	// Schließen über denselben Knopf lässt die Karte, wie sie ist.
	await pool.tap();
	await expect(pool).toHaveAttribute('aria-expanded', 'false');
	await karte.getByRole('button', { name: '+ Neu' }).click();
	await expect(pool).toHaveAttribute('aria-expanded', 'false');
});

test('Konto: drei Themen als Liste', async ({ page }) => {
	await schublade(page);
	await tab(page, 'Konto').click();
	for (const name of [/^Passwort ändern$/, /^Zwei-Faktor/, /^Passkeys$/]) {
		await expect(titel(page, name)).toHaveAttribute('aria-expanded', 'false');
	}
});
