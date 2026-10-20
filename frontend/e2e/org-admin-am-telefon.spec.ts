import { test, expect } from '@playwright/test';
import { orgAdmin } from './kontextmenue-attrappe';

// Org-Admin am Telefon: dieselben Klappkarten wie im Superadmin-Portal
// (`$lib/klappbar`), mit drei Zusagen, die man einem Bildschirmfoto nicht
// ansieht:
//
// - **Die eine Arbeitskarte eines Reiters startet offen** (Mitglieder,
//   GPS-Freigaben …) — zugeklappt wäre sie nur ein Tipp mehr bis zur Arbeit.
// - **Listen von Geräten und Seiten starten zu, ihr Zustand bleibt sichtbar.**
//   Am Tracker steht „bereit"/„wartet …" neben dem Namen, auch zugeklappt.
// - **Wer „Vorschau" tippt, sieht sie auch.** Der Knopf klappt seine Karte auf,
//   sonst erschiene die Vorschau in einer zugeklappten Karte.

const TELEFON = { width: 390, height: 844 };
const HUELLE = 'http://localhost:4174';

test.use({ viewport: TELEFON, hasTouch: true });

test('die Mitgliederliste startet offen und lässt sich trotzdem zuklappen', async ({ page }) => {
	await orgAdmin(page);
	const titel = page.getByRole('button', { name: /^Mitglieder \(\d+\)$/ });
	await expect(titel).toHaveAttribute('aria-expanded', 'true');
	await expect(page.getByRole('cell', { name: 'anna@example.org' })).toBeVisible();

	await titel.tap();
	await expect(titel).toHaveAttribute('aria-expanded', 'false');
	await expect(page.getByRole('cell', { name: 'anna@example.org' })).toBeHidden();
});

test('Tracker starten zu, der Zustand steht neben dem Namen', async ({ page }) => {
	await page.goto(`${HUELLE}/?k=tracker`);
	const karte = page.getByTestId('tracker').first();
	await expect(karte).toBeVisible();
	const titel = karte.locator('.klapp-titel');
	await expect(titel).toHaveAttribute('aria-expanded', 'false');
	// Zugeklappt: Kopfzeile mit Zustand und Knöpfen, darunter nichts.
	await expect(karte.locator('.marke')).toBeVisible();
	await expect(karte.getByRole('button', { name: 'Bearbeiten' })).toBeVisible();
	await expect(karte.locator('p.hint').first()).toBeHidden();

	await titel.tap();
	await expect(titel).toHaveAttribute('aria-expanded', 'true');
	await expect(karte.locator('p.hint').first()).toBeVisible();

	// Der Kopf der Liste ist zu, „+ Neuer Tracker" geht trotzdem.
	await page.getByRole('button', { name: '+ Neuer Tracker' }).click();
	await expect(page.getByRole('form', { name: 'Tracker' })).toBeVisible();
});

test('„Vorschau" klappt die Aktionsseite auf, damit man sie sieht', async ({ page }) => {
	await page.goto(`${HUELLE}/?k=aktion`);
	await page.getByRole('button', { name: '+ Neue Aktionsseite' }).click();
	const form = page.getByRole('form', { name: 'Aktionsseite' });
	await form.getByLabel('Titel', { exact: true }).fill('Test');
	await form.getByRole('button', { name: 'Anlegen' }).click();
	await page.getByRole('button', { name: 'Ich habe es übernommen' }).click();

	const karte = page.getByTestId('aktionsseite').first();
	await expect(karte.locator('.klapp-titel')).toHaveAttribute('aria-expanded', 'false');

	await karte.getByRole('button', { name: 'Vorschau', exact: true }).click();
	await expect(karte.locator('.klapp-titel')).toHaveAttribute('aria-expanded', 'true');
	await expect(page.getByTestId('vorschau')).toBeVisible();
	await expect(page.getByTestId('vorschau')).toContainText('Konvoi Bosnien');

	// Andere Knöpfe der Kopfzeile lassen den Zustand, wie er ist.
	await karte.locator('.klapp-titel').tap();
	await expect(karte.locator('.klapp-titel')).toHaveAttribute('aria-expanded', 'false');
	await karte.getByRole('button', { name: 'Vorschau schließen' }).click();
	await expect(karte.locator('.klapp-titel')).toHaveAttribute('aria-expanded', 'false');
});
