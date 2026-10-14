import { test, expect } from '@playwright/test';

// Telegram-Bot, Gruppen und Presse im Reiter Aktionsseiten (Plan 2026-10-13,
// § 8.4). Zusagen, die man einem Bildschirmfoto nicht ansieht:
//
// - Der Bot-Token steht nach dem Speichern nirgends mehr auf der Seite, auch
//   nicht im Wert eines Felds, und geht nur an den einen Aufruf, der ihn setzt.
// - Ein Code steht nur bis zu seinem Ablauf da und verschwindet ohne Neuladen.
// - Die Knöpfe schicken die Aufrufe aus § 8.3 — mit der Seite und dem Konvoi,
//   an dem sie stehen.
//
// Gemountet in der Hülle (`e2e/harness/`, `?k=aktion`), `$lib/api` gestubbt.

const HUELLE = 'http://localhost:4174/?k=aktion&mit_seite=1';
const TOKEN = '7712345678:AAFh3kQx9Lm2Pw8Zr5Tn1Vb6Yc4Hd0Gs7Jq';

async function aufrufe(page: import('@playwright/test').Page) {
	return (await page.evaluate(() => window.__telegramAufrufe)) ?? [];
}

test('der Bot-Token steht nach dem Speichern nirgends mehr', async ({ page }) => {
	await page.goto(HUELLE);
	const karte = page.getByTestId('telegram-bot');
	const feld = karte.getByLabel('Bot-Token');
	await feld.fill(TOKEN);
	await karte.getByRole('button', { name: 'Prüfen und speichern' }).click();

	await expect(karte).toContainText('@AktionsBot');
	await expect(karte).toContainText('bereit');
	await expect(page.locator('body')).not.toContainText(TOKEN);
	// Auch kein Feld trägt ihn noch als Wert.
	const werte = await page.locator('input').evaluateAll((els) => els.map((e) => (e as HTMLInputElement).value));
	expect(werte).not.toContain(TOKEN);
	expect(await page.content()).not.toContain(TOKEN);

	// Genau ein Aufruf trägt ihn: der, der ihn setzt.
	const mitToken = (await aufrufe(page)).filter((a) => JSON.stringify(a).includes(TOKEN));
	expect(mitToken).toEqual([['botSetzen', TOKEN]]);
});

test('sieht der Bot keine Fotos, sagt die Karte, was bei BotFather zu tun ist', async ({ page }) => {
	await page.goto(`${HUELLE}&privat=1`);
	const karte = page.getByTestId('telegram-bot');
	await karte.getByLabel('Bot-Token').fill(TOKEN);
	await karte.getByRole('button', { name: 'Prüfen und speichern' }).click();
	const hinweis = karte.getByTestId('privacy-hinweis');
	await expect(hinweis).toContainText('keine Fotos');
	await expect(hinweis).toContainText('/setprivacy');
});

test('ohne Bot gibt es keine Codes', async ({ page }) => {
	await page.goto(HUELLE);
	const fotos = page.getByTestId('fotos-von-unterwegs');
	await fotos.locator('summary').click();
	await expect(fotos).toContainText('Erst oben einen Telegram-Bot eintragen');
	await expect(fotos.getByRole('button', { name: 'Code erzeugen', exact: true })).toBeDisabled();
	await expect(fotos.getByRole('button', { name: 'Presse-Code erzeugen' })).toBeDisabled();
});

test('Gruppen und Presse: die Knöpfe schicken die Aufrufe der Seite und des Konvois', async ({ page }) => {
	page.on('dialog', (d) => d.accept());
	await page.goto(HUELLE);
	const karte = page.getByTestId('telegram-bot');
	await karte.getByLabel('Bot-Token').fill(TOKEN);
	await karte.getByRole('button', { name: 'Prüfen und speichern' }).click();
	await expect(karte).toContainText('@AktionsBot');

	const fotos = page.getByTestId('fotos-von-unterwegs');
	await fotos.locator('summary').click();
	await expect(fotos).toContainText('1 von 2 Konvois verbunden · 1 Presse');

	// Konvoi Rumänien hängt schon an einem Thema, Bosnien an nichts.
	const rumaenien = fotos.getByTestId('gruppe-c-rou');
	await expect(rumaenien).toContainText('Thema in „Weihnachtskonvoi 2026"');
	const bosnien = fotos.getByTestId('gruppe-c-bih');
	await bosnien.getByRole('button', { name: 'Code erzeugen', exact: true }).click();
	await expect(bosnien.getByTestId('verbinden-code')).toHaveText('/verbinden K7Q-2MX');

	await rumaenien.getByRole('button', { name: 'trennen' }).click();
	await expect(fotos.getByTestId('gruppe-c-rou')).toContainText('nicht verbunden');

	await fotos.getByRole('button', { name: 'Presse-Code erzeugen' }).click();
	await expect(fotos.getByTestId('presse-code')).toHaveText('/presse 4TR-8LK');
	await expect(fotos).toContainText('privat');

	await fotos.getByRole('button', { name: 'entfernen' }).click();
	await expect(fotos).toContainText('Noch niemand.');

	const gesendet = (await aufrufe(page)).filter((a) => !['seite', 'beitraege', 'botSetzen'].includes(a[0]));
	expect(gesendet).toEqual([
		['verbindenCode', 'a-1', 'c-bih'],
		['trennen', 'a-1', 'c-rou'],
		['presseCode', 'a-1'],
		['presseEntfernen', 'a-1', 55],
	]);
});

test('ein Code verschwindet bei seinem Ablauf, ohne Neuladen', async ({ page }) => {
	await page.goto(`${HUELLE}&code_s=2`);
	const karte = page.getByTestId('telegram-bot');
	await karte.getByLabel('Bot-Token').fill(TOKEN);
	await karte.getByRole('button', { name: 'Prüfen und speichern' }).click();
	const fotos = page.getByTestId('fotos-von-unterwegs');
	await fotos.locator('summary').click();
	const bosnien = fotos.getByTestId('gruppe-c-bih');
	await bosnien.getByRole('button', { name: 'Code erzeugen', exact: true }).click();
	await expect(bosnien.getByTestId('verbinden-code')).toBeVisible();
	await expect(bosnien.getByTestId('verbinden-code')).toHaveCount(0, { timeout: 5000 });
	await expect(bosnien.getByRole('button', { name: 'Code erzeugen', exact: true })).toBeEnabled();
});

test('Beiträge: Zähler auch zugeklappt, Aktionen wie die Knöpfe in Telegram', async ({ page }) => {
	await page.goto(HUELLE);
	const fotos = page.getByTestId('fotos-von-unterwegs');
	// Zugeklappt steht schon da, was wartet — und fällt auf.
	const zaehler = fotos.getByTestId('beitrag-zaehler');
	await expect(zaehler).toContainText('1 warten');
	await expect(zaehler).toContainText('0 in der Warteschlange · 1 öffentlich');
	await expect(zaehler.locator('.auffaellig')).toHaveText('1 warten');

	await fotos.locator('summary').click();
	const wartend = fotos.locator('[data-testid="beitrag"][data-status="wartet"]');
	await expect(wartend).toContainText('von Jonas');
	await expect(wartend.locator('.anzahl')).toHaveText('2');
	// Das Vorschaubild kommt von dieser Instanz, angemeldet — nicht von Telegram.
	await expect(wartend.locator('img')).toHaveAttribute('src', '/api/org/aktionsseiten/a-1/bilder/f-1/klein.webp');

	await wartend.getByRole('button', { name: 'Text ändern' }).click();
	await wartend.getByLabel('Öffentlicher Text').fill('Unterwegs nach Süden');
	await wartend.getByRole('button', { name: 'Text speichern' }).click();
	await expect(wartend).toContainText('„Unterwegs nach Süden"');
	await expect(wartend).toContainText('in Telegram: „Wir stehen an der A3 bei Würzburg"');
	await wartend.getByRole('button', { name: 'Freigeben' }).click();

	const frei = fotos.locator('[data-testid="beitrag"]', { hasText: 'Grenze geschafft' });
	await expect(frei).toContainText('öffentlich seit');
	await frei.getByRole('button', { name: 'Zurückziehen' }).click();
	await expect(frei).toContainText('zurückgezogen');

	const gesendet = (await aufrufe(page)).filter((a) => a[0] === 'beitragAendern');
	expect(gesendet).toEqual([
		['beitragAendern', 'a-1', 'p-wartet', { text_public: 'Unterwegs nach Süden' }],
		['beitragAendern', 'a-1', 'p-wartet', { aktion: 'frei' }],
		['beitragAendern', 'a-1', 'p-frei', { aktion: 'zurueck' }],
	]);
});
