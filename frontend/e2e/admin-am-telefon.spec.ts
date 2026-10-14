import { test, expect, type Page } from '@playwright/test';
import { adminBereich } from './kontextmenue-attrappe';

// Admin-Portal am Telefon. Zwei Zusagen, die man einem Bildschirmfoto nur halb
// ansieht:
//
// - **Die Reiterleiste zeigt, dass es weitergeht.** Vorher war die Scrollleiste
//   ausgeblendet, und die Leiste endete scheinbar nach drei Reitern.
// - **Lange Reiter sind eine Liste von Themen, keine Wand.** Am Telefon
//   starten die Karten zugeklappt, ein Tipp auf den Titel öffnet sie, und der
//   Browser merkt sich das.

const TELEFON = { width: 390, height: 844 };

const pfeil = (page: Page, seite: 'links' | 'rechts') =>
	page.getByRole('button', { name: `Weitere Reiter ${seite}` });
const leiste = (page: Page) => page.locator('.tab-leiste .tab-bar');
const titel = (page: Page, name: string) => page.getByRole('button', { name, exact: true });

test.describe('am Telefon', () => {
	test.use({ viewport: TELEFON, hasTouch: true });

	test('die Reiterleiste zeigt den Überlauf und blättert mit dem Pfeil', async ({ page }) => {
		await adminBereich(page);

		// Am Anfang: rechts geht es weiter, links nicht.
		await expect(pfeil(page, 'rechts')).toBeVisible();
		await expect(pfeil(page, 'links')).toHaveCount(0);
		// Verdeckte Reiter laufen aus, statt hart abgeschnitten zu sein.
		expect(await leiste(page).evaluate((el) => getComputedStyle(el).maskImage)).toContain('gradient');

		await pfeil(page, 'rechts').click();
		await expect.poll(() => leiste(page).evaluate((el) => el.scrollLeft)).toBeGreaterThan(0);
		await expect(pfeil(page, 'links')).toBeVisible();

		// Ganz am Ende verschwindet der rechte Pfeil.
		await leiste(page).evaluate((el) => { el.style.scrollBehavior = 'auto'; el.scrollLeft = el.scrollWidth; });
		await expect(pfeil(page, 'rechts')).toHaveCount(0);
		await expect(pfeil(page, 'links')).toBeVisible();
	});

	test('ein angeschnittener Reiter rollt beim Antippen ganz ins Bild', async ({ page }) => {
		await adminBereich(page);
		const reiter = page.locator('.tab', { hasText: 'Systemübersicht' });
		// So weit gerollt, dass vom Reiter rechts 60 px fehlen.
		await leiste(page).evaluate((el) => {
			el.style.scrollBehavior = 'auto';
			const t = [...el.querySelectorAll<HTMLElement>('.tab')].find((x) => x.textContent?.trim() === 'Systemübersicht')!;
			el.scrollLeft = t.offsetLeft + t.offsetWidth - 60 - el.clientWidth;
		});
		await expect(reiter).not.toBeInViewport({ ratio: 1 });
		await reiter.click({ position: { x: 10, y: 10 } });
		await expect(reiter).toHaveClass(/active/);
		await expect(reiter).toBeInViewport({ ratio: 1 });
	});

	test('die Karten im System-Reiter starten zugeklappt und merken sich den Zustand', async ({ page }) => {
		await adminBereich(page);
		const system = page.locator('.tab', { hasText: /^System$/ });
		await system.scrollIntoViewIfNeeded();
		await system.click();

		const smtp = titel(page, 'E-Mail (SMTP)');
		const lizenz = titel(page, 'Lizenz');
		await expect(smtp).toHaveAttribute('aria-expanded', 'false');
		await expect(lizenz).toHaveAttribute('aria-expanded', 'false');
		// Zugeklappt steht nur die Kopfzeile da.
		await expect(page.getByLabel('Host')).toBeHidden();

		await smtp.tap();
		await expect(smtp).toHaveAttribute('aria-expanded', 'true');
		await expect(page.getByText('Host', { exact: true })).toBeVisible();
		// Die anderen bleiben zu.
		await expect(lizenz).toHaveAttribute('aria-expanded', 'false');

		// Tastatur geht auch.
		await lizenz.focus();
		await page.keyboard.press('Enter');
		await expect(lizenz).toHaveAttribute('aria-expanded', 'true');
		await page.keyboard.press(' ');
		await expect(lizenz).toHaveAttribute('aria-expanded', 'false');

		// Nach dem Neuladen gilt, was jemand gewählt hat, nicht der Standard.
		await page.reload();
		await expect(page.getByRole('cell', { name: 'anna@example.org' })).toBeVisible();
		await page.locator('.tab', { hasText: /^System$/ }).click();
		await expect(titel(page, 'E-Mail (SMTP)')).toHaveAttribute('aria-expanded', 'true');
		await expect(titel(page, 'Lizenz')).toHaveAttribute('aria-expanded', 'false');
	});

	test('Knöpfe in der Kopfzeile bleiben bedienbar und klappen nicht', async ({ page }) => {
		const aufrufe: string[] = [];
		await adminBereich(page);
		page.on('request', (r) => { if (r.url().includes('/api/license/status')) aufrufe.push(r.url()); });
		const system = page.locator('.tab', { hasText: /^System$/ });
		await system.scrollIntoViewIfNeeded();
		await system.click();

		const karte = page.locator('.section', { has: titel(page, 'Lizenz') });
		const vorher = aufrufe.length;
		await karte.locator('.section-header .btn-small').click();
		await expect.poll(() => aufrufe.length).toBeGreaterThan(vorher);
		await expect(titel(page, 'Lizenz')).toHaveAttribute('aria-expanded', 'false');
	});
});

test('am Schreibtisch starten die Karten offen', async ({ page }) => {
	await adminBereich(page);
	await page.locator('.tab', { hasText: /^System$/ }).click();
	await expect(titel(page, 'E-Mail (SMTP)')).toHaveAttribute('aria-expanded', 'true');
	await expect(page.getByText('Host', { exact: true })).toBeVisible();
	// Zuklappen geht trotzdem.
	await titel(page, 'E-Mail (SMTP)').click();
	await expect(page.getByText('Host', { exact: true })).toBeHidden();
});
