import { test, expect, type Page } from '@playwright/test';
import { GRUNDLAGE, mockApi } from './kontextmenue-attrappe';

// Die kleinen Seiten am Telefon: Anmeldung, Demo, Fehlerseite. Zusagen, die
// man einem Bildschirmfoto nur halb ansieht:
//
// - **Karten halten Abstand zum Rand.** Als Rand diente nur die Safe-Area; auf
//   einem Telefon ohne Notch lief die 380 px breite Karte bis auf 5 px an den
//   Bildschirmrand.
// - **Die Fehlerseite ist lesbar und führt zurück.** Vorher stand die Vorgabe
//   von SvelteKit da — schwarze Schrift auf dunklem Grund, ohne Weg zurück.
// - **Eine unbekannte Adresse bleibt die 404, auch ohne Sitzung.** Der Wächter
//   im Wurzel-Layout schickte sie auf die Superadmin-Anmeldung, sobald
//   `auth.init()` geantwortet hatte; der Test sah die 404 nur, wenn er
//   schneller war (3 von 8 Läufen rot).

const TELEFON = { width: 390, height: 844 };
test.use({ viewport: TELEFON, hasTouch: true });

async function oeffnen(page: Page, pfad: string) {
	// Ohne Sitzung: Die Attrappe meldet sonst einen angemeldeten Superadmin, und /admin
	// zeigte das Portal statt der Anmeldung.
	const { 'GET /api/auth/me': _sitzung, ...ohneSitzung } = GRUNDLAGE;
	await mockApi(page, ohneSitzung);
	// Erst wenn beide beantwortet sind, entscheidet der Wächter im Wurzel-Layout
	// (`setupChecked` und `$auth.ready`). Wer vorher prüft, prüft den Zustand,
	// bevor der Wächter umleiten konnte.
	const entschieden = Promise.all([
		page.waitForResponse((r) => new URL(r.url()).pathname === '/api/setup/status'),
		page.waitForResponse((r) => new URL(r.url()).pathname === '/api/auth/me'),
	]);
	await page.goto(pfad, { waitUntil: 'domcontentloaded' });
	await entschieden;
	// Ein `goto('/admin')` lädt erst den Code der Zielseite und ändert die Adresse
	// danach; zwei Frames nach der Antwort ist sie noch die alte. Erst wenn das Netz
	// ruhig ist, hätte eine Umleitung stattgefunden.
	await page.waitForLoadState('networkidle');
}

for (const [name, pfad, karte] of [
	['Startseite', '/', '.login-card'],
	['Superadmin-Anmeldung', '/admin', '.login-card'],
	['Demo', '/demo', '.demo-card'],
	['Demo abmelden', '/demo/abmelden', '.card'],
] as const) {
	test(`${name}: die Karte hält mindestens 15 px Abstand zum Rand`, async ({ page }) => {
		await oeffnen(page, pfad);
		const k = page.locator(karte).first();
		await expect(k).toBeVisible();
		const b = (await k.boundingBox())!;
		expect(b.x, 'links').toBeGreaterThanOrEqual(15);
		expect(TELEFON.width - (b.x + b.width), 'rechts').toBeGreaterThanOrEqual(15);
	});
}

test('die Fehlerseite ist lesbar und führt zur Startseite', async ({ page }) => {
	await oeffnen(page, '/gibt-es-nicht');
	expect(new URL(page.url()).pathname, 'keine Umleitung auf die Anmeldung').toBe('/gibt-es-nicht');
	const titel = page.getByRole('heading', { name: 'Seite nicht gefunden' });
	await expect(titel).toBeVisible();
	await expect(page.getByText('Fehler 404')).toBeVisible();

	// Helle Schrift auf dunklem Grund — nicht die schwarze Vorgabe von SvelteKit.
	const farbe = await titel.evaluate((el) => getComputedStyle(el).color);
	expect(farbe).not.toBe('rgb(0, 0, 0)');

	await expect(page.getByRole('link', { name: 'Zur Startseite →' })).toHaveAttribute('href', '/');
});
