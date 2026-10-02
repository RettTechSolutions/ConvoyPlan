import { test, expect } from '@playwright/test';

// Die Verwaltung der öffentlichen Aktionsseiten im Org-Admin. Zusagen, die man
// einem Bildschirmfoto nicht ansieht:
//
// - Das Abruf-Token steht genau einmal da — nach dem Anlegen, mit dem fertigen
//   Eintrag für den EventTracker — und ist nach dem Neuladen weg.
// - Unter einer Stunde Verzögerung lässt sich nichts einstellen.
// - Der interne Konvoiname geht nicht als öffentlicher Name hinaus: Ohne
//   eigenen Namen lässt sich ein gewählter Konvoi nicht speichern.
//
// Gemountet in der Hülle (`e2e/harness/`, `?k=aktion`), `$lib/api` gestubbt.

const HUELLE = 'http://localhost:4174/?k=aktion';

test('Anlegen zeigt das Token einmal, mit dem Eintrag für den EventTracker', async ({ page }) => {
	await page.goto(HUELLE);
	await page.getByRole('button', { name: '+ Neue Aktionsseite' }).click();

	const form = page.getByRole('form', { name: 'Aktionsseite' });
	await form.getByLabel('Titel', { exact: true }).fill('Weihnachtskonvois 2026');
	await form.getByLabel('Gestaltung').selectOption('weihnachten');
	await form.getByLabel('KV 3 / Los B Ladeliste').check();

	// Gewählt, aber ohne öffentlichen Namen: nicht speicherbar.
	const anlegen = form.getByRole('button', { name: 'Anlegen' });
	await expect(anlegen).toBeDisabled();
	await form.getByLabel('Öffentlicher Name').fill('Konvoi Bosnien');
	await form.getByLabel('Ziel optional').fill('Tuzla');
	await anlegen.click();

	const box = page.getByTestId('neues-token');
	await expect(box).toContainText('nur jetzt');
	const eintrag = JSON.parse((await box.locator('pre').textContent()) ?? '{}');
	expect(eintrag).toEqual({
		pfad: 'weihnachtskonvois-2026',
		slug: 'Hq3vT8kLm2Pw',
		token: 'tok_Zr8Qm2Lw5Xc9Vb3Nh7Kp',
	});
	await expect(box).toContainText('CONVOYPLAN_URL=https://einsatz.example.de');

	// Was abgeschickt wurde: der öffentliche Name, nicht der interne.
	const gesendet = await page.evaluate(() => window.__aktionAngelegt);
	expect(gesendet?.convoys).toEqual([
		{ convoy_id: 'c-bih', display_name: 'Konvoi Bosnien', destination_label: 'Tuzla', color: null },
	]);
	expect(gesendet?.delay_minutes).toBe(120);

	// Bestätigt: Box weg, die Seite steht in der Liste — ohne Token.
	await box.getByRole('button', { name: 'Ich habe es übernommen' }).click();
	await expect(box).toHaveCount(0);
	const seite = page.getByTestId('aktionsseite');
	await expect(seite).toContainText('Weihnachtskonvois 2026');
	await expect(seite).toContainText('Konvoi Bosnien');
	await expect(page.locator('body')).not.toContainText('tok_Zr8Qm2Lw5Xc9Vb3Nh7Kp');
});

test('unter einer Stunde Verzögerung gibt es nicht zur Auswahl', async ({ page }) => {
	await page.goto(HUELLE);
	await page.getByRole('button', { name: '+ Neue Aktionsseite' }).click();
	const werte = await page
		.getByLabel('Verzögerung')
		.locator('option')
		.evaluateAll((o) => o.map((x) => Number((x as HTMLOptionElement).value)));
	expect(Math.min(...werte)).toBeGreaterThanOrEqual(60);
	await expect(page.getByLabel('Verzögerung')).toHaveValue('120');
});

test('die Vorschau sagt, was vergröbert ist', async ({ page }) => {
	await page.goto(HUELLE);
	await page.getByRole('button', { name: '+ Neue Aktionsseite' }).click();
	const form = page.getByRole('form', { name: 'Aktionsseite' });
	await form.getByLabel('Titel', { exact: true }).fill('Test');
	await form.getByRole('button', { name: 'Anlegen' }).click();
	await page.getByRole('button', { name: 'Ich habe es übernommen' }).click();

	await page.getByRole('button', { name: 'Vorschau', exact: true }).click();
	const v = page.getByTestId('vorschau');
	await expect(v).toContainText('Konvoi Bosnien');
	await expect(v).toContainText('vergröbert');
	await expect(v).toContainText('120 Min. verzögert');
});
