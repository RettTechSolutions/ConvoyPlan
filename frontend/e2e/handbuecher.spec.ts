import { test, expect, type Page } from '@playwright/test';
import { blockExternal } from './fixtures';
import { GRUNDLAGE, mockApi } from './kontextmenue-attrappe';
import { readFileSync } from 'node:fs';

// Gelesen, nicht importiert: Playwright läuft in `frontend/`, und so prüft der Test
// genau die Datei, die auch die Seite liest.
const katalog: { datei: string; titel: string; bytes: number }[] = JSON.parse(
	readFileSync('src/lib/handbuecher/katalog.json', 'utf8'),
);

// Die Handbücher als PDF. Zusagen, die man der Seite nicht ansieht:
//
// - **Jedes gelistete Handbuch ist da**, als PDF, von dieser Instanz — kein
//   Verweis nach GitHub, der ohne Internet ins Leere ginge, und kein Eintrag im
//   Katalog, dessen Datei beim Erzeugen liegen geblieben ist.
// - **Man findet sie ohne Anmeldung** (Fußzeile der Startseite) und aus der
//   Planung heraus, ohne sie zu verlassen (neuer Reiter).

const HUELLE = 'http://localhost:4174';

async function ohneSitzung(page: Page) {
	const { 'GET /api/auth/me': _sitzung, ...rest } = GRUNDLAGE;
	await mockApi(page, rest);
}

test('die Seite listet jedes Handbuch, und jedes ist ein PDF dieser Instanz', async ({ page, request }) => {
	expect(katalog.length).toBeGreaterThanOrEqual(3);
	await ohneSitzung(page);
	await page.goto('/handbuecher', { waitUntil: 'domcontentloaded' });
	await expect(page.getByRole('heading', { name: 'Handbücher', level: 1 })).toBeVisible();

	const links = page.getByRole('link', { name: 'PDF öffnen' });
	await expect(links).toHaveCount(katalog.length);

	for (const [i, h] of katalog.entries()) {
		await expect(page.getByRole('heading', { name: h.titel })).toBeVisible();
		await expect(links.nth(i)).toHaveAttribute('href', `/handbuecher/${h.datei}`);
		await expect(links.nth(i)).toHaveAttribute('target', '_blank');

		const antwort = await request.get(`/handbuecher/${h.datei}`);
		expect(antwort.status(), h.datei).toBe(200);
		expect(antwort.headers()['content-type']).toContain('application/pdf');
		const inhalt = await antwort.body();
		expect(inhalt.subarray(0, 5).toString(), h.datei).toBe('%PDF-');
		// Größe aus demselben Lauf wie die Datei — sonst nennt die Seite eine falsche.
		expect(inhalt.length, `${h.datei}: Katalog und Datei passen nicht zusammen`).toBe(h.bytes);
	}
});

test('ohne Anmeldung: die Fußzeile der Startseite führt zu den Handbüchern', async ({ page }) => {
	await ohneSitzung(page);
	await page.goto('/', { waitUntil: 'domcontentloaded' });
	const link = page.locator('.legal-footer').getByRole('link', { name: 'Handbücher' });
	await expect(link).toHaveAttribute('href', '/handbuecher');
	await link.click();
	await expect(page).toHaveURL(/\/handbuecher$/);
	await expect(page.getByRole('heading', { name: 'Handbücher', level: 1 })).toBeVisible();
});

test('am Telefon: nichts ragt seitlich heraus', async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await ohneSitzung(page);
	await page.goto('/handbuecher', { waitUntil: 'domcontentloaded' });
	await expect(page.getByRole('link', { name: 'PDF öffnen' }).first()).toBeVisible();
	const breite = await page.evaluate(() => document.documentElement.scrollWidth);
	expect(breite).toBeLessThanOrEqual(390);
});

test('aus der Planung: das Handbuch öffnet in einem neuen Reiter', async ({ page }) => {
	await blockExternal(page);
	await page.goto(`${HUELLE}/?k=fuss`);
	const link = page.locator('[data-tour="sidebar-footer"]').getByRole('link', { name: 'Handbücher (PDF)' });
	await expect(link).toHaveAttribute('href', '/handbuecher');
	await expect(link).toHaveAttribute('target', '_blank');
});
