import { test, expect } from '@playwright/test';

// Geht ein fälliger Halt in einem geplanten auf („Tankhalt + TH"), entfällt
// er nicht — die WOLKE-Prüfung findet am Tankhalt statt. Die Zusagen:
//  - der Wegpunkt trägt eine Marke, die sagt, welcher Halt dort mit erledigt wird;
//  - der volle Text nennt die empfohlene Dauer, wenn der Halt kürzer geplant ist,
//    und nur dann;
//  - ein Wegpunkt ohne zusammengelegten Halt trägt keine Marke.

const HUELLE = 'http://localhost:4174';

test.beforeEach(async ({ page }) => {
	await page.goto(`${HUELLE}/?k=vermerk`);
	await expect(page.getByTestId('tankhalt')).toBeVisible();
});

test('der Tankhalt sagt, dass dort auch der Technische Halt stattfindet', async ({ page }) => {
	const marke = page.getByTestId('tankhalt').getByRole('note');
	await expect(marke).toHaveText('+ TH');
	await expect(marke).toHaveAccessibleName('zugleich Technischer Halt (WOLKE), empfohlen 30 min');
});

test('die empfohlene Dauer steht nur dabei, wenn der Halt kürzer ist', async ({ page }) => {
	const marke = page.getByTestId('pause').getByRole('note');
	await expect(marke).toHaveText('+ Lenkpause');
	await expect(marke).toHaveAccessibleName('zugleich Lenkpause');
});

test('ohne zusammengelegten Halt keine Marke', async ({ page }) => {
	await expect(page.getByTestId('kontrollpunkt').getByRole('note')).toHaveCount(0);
});
