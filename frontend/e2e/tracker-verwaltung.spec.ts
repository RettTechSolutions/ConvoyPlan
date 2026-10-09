import { test, expect } from '@playwright/test';

// Die Verwaltung der Tracker im Org-Admin. Zusagen, die man einem
// Bildschirmfoto nicht ansieht:
//
// - Der Einmal-Code steht genau einmal da — nach dem Anlegen — und ist nach
//   dem Bestätigen weg; in der Liste taucht er nie auf.
// - Ein Fahrzeug, an dem schon ein Tracker hängt, steht nicht zur Wahl.
// - Ohne Fahrzeug geht das Anlegen, aber die Liste sagt „ohne Fahrzeug".
//
// Gemountet in der Hülle (`e2e/harness/`, `?k=tracker`), `$lib/api` gestubbt.

const HUELLE = 'http://localhost:4174/?k=tracker';

test('Anlegen zeigt den Code einmal, danach steht der Tracker ohne Code in der Liste', async ({ page }) => {
	await page.goto(HUELLE);
	await expect(page.getByTestId('tracker')).toHaveCount(1);
	await page.getByRole('button', { name: '+ Neuer Tracker' }).click();

	const form = page.getByRole('form', { name: 'Tracker' });
	const anlegen = form.getByRole('button', { name: 'Anlegen' });
	await expect(anlegen).toBeDisabled();
	await form.getByLabel('Name').fill('Tracker HLF 20');
	await form.getByLabel('Fahrzeug').selectOption('v-hlf');
	await form.getByLabel('Update-Kanal').selectOption('beta');
	await anlegen.click();

	const box = page.getByTestId('neuer-code');
	await expect(box).toContainText('nur jetzt');
	await expect(box.locator('pre')).toHaveText('K7Q2-M9XD');

	const gesendet = await page.evaluate(() => window.__trackerAngelegt);
	expect(gesendet).toEqual({ name: 'Tracker HLF 20', vehicle_id: 'v-hlf', kanal: 'beta', aktiv: true });

	await box.getByRole('button', { name: 'Ich habe ihn eingegeben' }).click();
	await expect(box).toHaveCount(0);
	const zeilen = page.getByTestId('tracker');
	await expect(zeilen).toHaveCount(2);
	await expect(zeilen.nth(1)).toContainText('Tracker HLF 20');
	await expect(zeilen.nth(1)).toContainText('HLF 20');
	await expect(zeilen.nth(1)).toContainText('wartet auf Einrichtung');
	await expect(page.locator('body')).not.toContainText('K7Q2-M9XD');
});

test('ein Fahrzeug mit Tracker steht nicht zur Wahl', async ({ page }) => {
	await page.goto(HUELLE);
	await page.getByRole('button', { name: '+ Neuer Tracker' }).click();
	const werte = await page
		.getByRole('form', { name: 'Tracker' })
		.getByLabel('Fahrzeug')
		.locator('option')
		.evaluateAll((o) => o.map((x) => (x as HTMLOptionElement).value));
	// LF 10 hat schon einen Tracker; das leere Feld bleibt als „kein Fahrzeug".
	expect(werte).toEqual(['', 'v-hlf', 'v-mtw']);
});

test('ein eingerichteter Tracker zeigt, was das Gerät gemeldet hat', async ({ page }) => {
	await page.goto(HUELLE);
	const zeile = page.getByTestId('tracker').first();
	await expect(zeile).toContainText('bereit');
	await expect(zeile).toContainText('Akku 87 %');
	await expect(zeile).toContainText('Firmware 0.1.0');
	await expect(zeile).toContainText('352656100000002');
});
