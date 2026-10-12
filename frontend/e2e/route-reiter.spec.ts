import { test, expect, type Page } from '@playwright/test';

// Die Ergebnisse der Routenberechnung — Tankstopp, empfohlene Halte,
// Durchfahrtshöhen, Gewichtsgrenzen — stehen im eigenen Reiter „Route" und
// nicht mehr im Reiter „Plan". Damit dort nichts ungesehen liegen bleibt,
// trägt der Reiter eine Marke. Die Zusagen:
//  - die Zahl nennt, was noch zu tun oder zu prüfen ist: ein fehlender
//    Tankstopp, jeder noch nicht gesetzte Halt, jede Stelle, die nicht frei ist;
//  - was schon als Wegpunkt steht, zählt nicht mehr;
//  - rot wird sie bei fehlendem Tankstopp, enger Durchfahrt, überschrittener
//    Grenze — sonst bleibt sie gelb;
//  - ohne Hinweis (und ohne Route) steht keine Marke da, auch keine „0".

const HUELLE = 'http://localhost:4174';
const marke = (page: Page) => page.getByRole('status');

async function oeffnen(page: Page, fall: string) {
	await page.goto(`${HUELLE}/?k=route&fall=${fall}`);
	await expect(page.getByRole('button', { name: /^Route/ })).toBeVisible();
}

const farbe = (page: Page) => marke(page).evaluate((el) => getComputedStyle(el).backgroundColor);

test('ohne Hinweis steht keine Marke da', async ({ page }) => {
	for (const fall of ['keine', 'tankstopp_gesetzt', 'ohne_route']) {
		await oeffnen(page, fall);
		await expect(marke(page)).toHaveCount(0);
	}
});

test('jeder noch nicht gesetzte Halt zählt, ein gesetzter nicht mehr', async ({ page }) => {
	await oeffnen(page, 'halte');
	await expect(marke(page)).toHaveText('2');
	await expect(marke(page)).toHaveAccessibleName('2 Hinweise zur Route');
	await oeffnen(page, 'halte_teils_gesetzt');
	await expect(marke(page)).toHaveText('1');
	await expect(marke(page)).toHaveAccessibleName('1 Hinweis zur Route');
});

test('eine enge Durchfahrt und ein fehlender Tankstopp färben die Marke rot', async ({ page }) => {
	await oeffnen(page, 'knapp');
	await expect(marke(page)).toHaveText('1');
	const gelb = await farbe(page);

	await oeffnen(page, 'eng');
	await expect(marke(page)).toHaveText('2');
	const rot = await farbe(page);
	expect(rot).not.toBe(gelb);

	await oeffnen(page, 'tankstopp');
	await expect(marke(page)).toHaveText('1');
	expect(await farbe(page)).toBe(rot);
});
