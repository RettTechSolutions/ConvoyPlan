import { test, expect, type Page } from '@playwright/test';

// Gewichtsgrenzen in der Planungsansicht. Gesperrt hat das Routing schon —
// außer bei „Anlieger frei", das nur gemieden wird. Die Zusagen:
//  - überschrittene und knappe Grenzen stehen sofort da, mit Kilometer,
//    Grenze, Reserve und Ausnahme; die freien nur auf Nachfrage;
//  - eine überschrittene Grenze färbt den Block, damit sie nicht in der
//    Seitenleiste untergeht;
//  - ohne Fahrzeuggewicht sagt der Block, dass nichts gemieden wurde;
//  - „nicht ermittelt" zeigt nichts — „keine Grenze" wäre eine Behauptung;
//  - Achslastgrenzen stehen in derselben Liste, als solche benannt;
//  - wie gerundet wird und ab wann etwas knapp ist, steht immer dabei.

const HUELLE = 'http://localhost:4174';
const block = (page: Page) => page.getByRole('region', { name: 'Gewichtsgrenzen' });
const eintraege = (page: Page) =>
	block(page).getByRole('list', { name: 'Gewichtsgrenzen an der Route' }).getByRole('listitem');

async function oeffnen(page: Page, fall: string) {
	await page.goto(`${HUELLE}/?k=gewicht&fall=${fall}`);
	await expect(page.getByText('Route berechnet.')).toBeVisible();
}

test('überschrittene und knappe Grenzen stehen da, die freien auf Nachfrage', async ({ page }) => {
	await oeffnen(page, 'gemischt');
	await expect(block(page)).toContainText('Schwerstes Fahrzeug: 26,0 t');
	await expect(block(page)).toContainText('2 Fahrzeuge ohne Gewicht, nicht berücksichtigt');
	await expect(block(page)).toContainText('Größte Achslast: 9,5 t');
	await expect(eintraege(page)).toHaveCount(3);
	await expect(eintraege(page).nth(0)).toContainText('km 3,1');
	await expect(eintraege(page).nth(0)).toContainText('7,5 t');
	await expect(eintraege(page).nth(0)).toContainText('−18,5 t');
	await expect(eintraege(page).nth(0)).toContainText('Anlieger frei');
	await expect(eintraege(page).nth(0)).toContainText('über der Grenze');
	await expect(eintraege(page).nth(1)).toContainText('+1,5 t');
	await expect(eintraege(page).nth(1)).toContainText('knapp');

	await expect(eintraege(page).nth(2)).toContainText('Achslast 10,0 t');
	await expect(eintraege(page).nth(2)).toContainText('+0,5 t');

	await block(page).getByRole('button', { name: '+ 1 weitere mit ausreichender Reserve' }).click();
	await expect(eintraege(page)).toHaveCount(4);
	await expect(eintraege(page).nth(1)).toContainText('40,0 t');
});

test('eine überschrittene Grenze färbt den Block', async ({ page }) => {
	await oeffnen(page, 'gemischt');
	const rot = await block(page).evaluate((el) => getComputedStyle(el).borderTopColor);
	await oeffnen(page, 'alle_frei');
	const grau = await block(page).evaluate((el) => getComputedStyle(el).borderTopColor);
	expect(rot).not.toBe(grau);
});

test('sind alle frei, sagt der Block das in einem Satz', async ({ page }) => {
	await oeffnen(page, 'alle_frei');
	await expect(block(page)).toContainText('1 Grenze, alle mit ausreichender Reserve.');
	await expect(eintraege(page)).toHaveCount(0);
});

test('ohne Fahrzeuggewicht wird nichts als unbedenklich gezeigt', async ({ page }) => {
	await oeffnen(page, 'ohne_gewicht');
	await expect(block(page)).toContainText('Kein Fahrzeuggewicht erfasst – die Route meidet keine Gewichtsgrenze.');
	await expect(eintraege(page).first()).toContainText('Gewicht fehlt');
});

test('ohne Grenze auf der Strecke steht das da', async ({ page }) => {
	await oeffnen(page, 'leer');
	await expect(block(page)).toContainText('Keine Gewichtsgrenze auf der Strecke bekannt.');
});

test('nicht ermittelt zeigt keinen Block', async ({ page }) => {
	await oeffnen(page, 'alt');
	await expect(block(page)).toHaveCount(0);
});

test('wie gerundet wird und ab wann es knapp ist, steht immer dabei', async ({ page }) => {
	for (const fall of ['gemischt', 'ohne_gewicht', 'leer']) {
		await oeffnen(page, fall);
		await expect(block(page)).toContainText('Gewicht auf 0,1 t, Achslast auf 0,5 t gerundet');
		await expect(block(page)).toContainText('unter 2 t Reserve beim Gewicht, unter 1 t bei der Achslast');
	}
});
