import { test, expect, type Page } from '@playwright/test';
import { BENUTZER, GRUNDLAGE, ORGS, adminBereich, mockApi } from './kontextmenue-attrappe';

// Admin-Portal am Telefon. Zwei Zusagen, die man einem Bildschirmfoto nur halb
// ansieht:
//
// - **Die Reiterleiste zeigt, dass es weitergeht.** Vorher war die Scrollleiste
//   ausgeblendet, und die Leiste endete scheinbar nach drei Reitern.
// - **Lange Reiter sind eine Liste von Themen, keine Wand.** Am Telefon
//   starten die Karten zugeklappt, ein Tipp auf den Titel öffnet sie, und der
//   Browser merkt sich das.
// - **Was ansteht, steht in der Kopfzeile.** Ein verfügbares Update oder ein
//   laufender Graph-Aufbau fällt auch an der zugeklappten Karte auf.

const TELEFON = { width: 390, height: 844 };

const pfeil = (page: Page, seite: 'links' | 'rechts') =>
	page.getByRole('button', { name: `Weitere Reiter ${seite}` });
const leiste = (page: Page) => page.locator('.tab-leiste .tab-bar');
// „System" und nicht „Systemübersicht"; ein Hinweis am Reiter darf dahinter stehen.
const systemReiter = (page: Page) => page.locator('.tab', { hasText: /^System(?!übersicht)/ });
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
		const system = systemReiter(page);
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
		await systemReiter(page).click();
		await expect(titel(page, 'E-Mail (SMTP)')).toHaveAttribute('aria-expanded', 'true');
		await expect(titel(page, 'Lizenz')).toHaveAttribute('aria-expanded', 'false');
	});

	test('Knöpfe in der Kopfzeile bleiben bedienbar und klappen nicht', async ({ page }) => {
		const aufrufe: string[] = [];
		await adminBereich(page);
		page.on('request', (r) => { if (r.url().includes('/api/license/status')) aufrufe.push(r.url()); });
		const system = systemReiter(page);
		await system.scrollIntoViewIfNeeded();
		await system.click();

		const karte = page.locator('.section', { has: titel(page, 'Lizenz') });
		const vorher = aufrufe.length;
		await karte.locator('.section-header .btn-small').click();
		await expect.poll(() => aufrufe.length).toBeGreaterThan(vorher);
		await expect(titel(page, 'Lizenz')).toHaveAttribute('aria-expanded', 'false');
	});
});

test.describe('Status in der Kopfzeile', () => {
	test.use({ viewport: TELEFON, hasTouch: true });

	const STAND = {
		deployed_sha: 'aaaaaaa', deployed_at: null, remote_sha: 'bbbbbbb', update_available: true,
		github_reachable: true, channel: 'stable', latest_release: 'v2026.10.0', no_release: false,
		ahead_of_release: false, held_back: null,
	};

	async function updateKarte(page: Page, stand: object) {
		await mockApi(page, {
			...GRUNDLAGE,
			'GET /api/admin/users': BENUTZER,
			'GET /api/admin/organizations': ORGS,
			'GET /api/admin/update-status': stand,
		});
		await page.goto('/admin', { waitUntil: 'domcontentloaded' });
		await expect(page.getByRole('cell', { name: 'anna@example.org' })).toBeVisible();
		const system = systemReiter(page);
		await system.scrollIntoViewIfNeeded();
		await system.click();
		return page.locator('.section', { has: titel(page, 'Software-Update') });
	}

	test('ein verfügbares Update steht an der zugeklappten Karte', async ({ page }) => {
		const karte = await updateKarte(page, STAND);
		await expect(titel(page, 'Software-Update')).toHaveAttribute('aria-expanded', 'false');
		await expect(karte.getByTestId('kopf-status')).toHaveText('Update verfügbar');
		await expect(karte.getByTestId('kopf-status')).toBeVisible();
	});

	test('zurückgehalten und aktuell heißen auch so', async ({ page }) => {
		const karte = await updateKarte(page, {
			...STAND, held_back: { since: '2026-10-14T08:00:00Z', users: 2, demo_users: 0 },
		});
		await expect(karte.getByTestId('kopf-status')).toHaveText('Update zurückgehalten');

		const aktuell = await updateKarte(page, { ...STAND, update_available: false, remote_sha: 'aaaaaaa' });
		await expect(aktuell.getByTestId('kopf-status')).toHaveText('Aktuell');
	});

	test('der Reiter „System" zeigt ein verfügbares Update, der Pfeil davor auch', async ({ page }) => {
		await updateKarte(page, STAND);
		await leiste(page).evaluate((el) => { el.style.scrollBehavior = 'auto'; el.scrollLeft = 0; });
		// Am Telefon liegt „System" hinter dem rechten Pfeil — der trägt deshalb einen Punkt.
		await expect(pfeil(page, 'rechts')).toHaveClass(/meldung/);
		await expect(systemReiter(page).getByTestId('system-hinweis')).toHaveText('↑');
		await expect(page.getByRole('button', { name: 'System – Update verfügbar' })).toHaveCount(1);

		// Ganz nach rechts gerollt: Reiter sichtbar, kein Pfeil mehr nötig.
		await leiste(page).evaluate((el) => { el.scrollLeft = el.scrollWidth; });
		await expect(pfeil(page, 'rechts')).toHaveCount(0);
		await expect(systemReiter(page).getByTestId('system-hinweis')).toBeInViewport();
	});

	test('ohne anstehendes Update kein Hinweis am Reiter und kein Punkt am Pfeil', async ({ page }) => {
		await updateKarte(page, { ...STAND, update_available: false, remote_sha: 'aaaaaaa' });
		await leiste(page).evaluate((el) => { el.style.scrollBehavior = 'auto'; el.scrollLeft = 0; });
		await expect(pfeil(page, 'rechts')).toBeVisible();
		await expect(pfeil(page, 'rechts')).not.toHaveClass(/meldung/);
		await expect(page.getByTestId('system-hinweis')).toHaveCount(0);
	});

	test('die Kartenregion meldet einen laufenden oder hängenden Graph-Aufbau', async ({ page }) => {
		const status = page.locator('.region-card .section-header').getByTestId('kopf-status');
		for (const [bau, text] of [['import', 'Graph wird gebaut'], ['haengt', 'Graph-Aufbau hängt']]) {
			await page.goto(`http://localhost:4174/?k=region&bau=${bau}`);
			await expect(page.getByText('dach-latest.osm.pbf')).toBeAttached(); // zugeklappt, aber geladen
			await expect(status).toHaveText(text);
			await expect(status).toBeVisible();
		}
		// Ohne Bau gibt es nichts zu melden.
		await page.goto('http://localhost:4174/?k=region&bau=keiner');
		await expect(page.getByText('dach-latest.osm.pbf')).toBeAttached(); // zugeklappt, aber geladen
		await expect(status).toHaveCount(0);
	});
});

test('am Schreibtisch starten die Karten offen', async ({ page }) => {
	await adminBereich(page);
	await systemReiter(page).click();
	await expect(titel(page, 'E-Mail (SMTP)')).toHaveAttribute('aria-expanded', 'true');
	await expect(page.getByText('Host', { exact: true })).toBeVisible();
	// Zuklappen geht trotzdem.
	await titel(page, 'E-Mail (SMTP)').click();
	await expect(page.getByText('Host', { exact: true })).toBeHidden();
});
