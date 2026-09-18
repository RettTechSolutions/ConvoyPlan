import { test, expect, type Page } from '@playwright/test';
import { blockExternal, mockOrgPortal } from './fixtures';

/**
 * Die Zusage: **wer eine Org-Seite direkt aufruft, ist in dieser Organisation
 * angemeldet** — auch beim harten Laden, wo sonst niemand die Adresszeile
 * gelesen hat.
 *
 * Das war einmal anders. Die Organisation stand in einer Modulvariablen, die
 * das Org-Layout vor seinen Aufrufen setzte; das Wurzel-Layout mountet danach
 * und stellte sie über `auth.init()` wieder auf „keine Organisation". Jede
 * Anfrage, die danach hinausging — und das sind alle Daten der Seite —, landete
 * auf der organisationslosen Sitzung. In der Tracking-Ansicht stand deshalb
 * „Marschverband konnte nicht geladen werden: Org context required", während
 * der Live-Kanal daneben fröhlich „Live" meldete: der prüft die Person, nicht
 * die Organisation.
 *
 * Sichtbar wird das nur bei einem echten Seitenaufbau, nicht beim Klicken
 * innerhalb des Portals — also genau so, wie dieser Test die Seite öffnet.
 */

const SLUG = 'thw-musterstadt';
const CONVOY = '11111111-1111-1111-1111-111111111111';

async function oeffnen(page: Page) {
	await blockExternal(page);
	await mockOrgPortal(page, { slug: SLUG, convoyId: CONVOY });
	await page.goto(`/o/${SLUG}/tracking/${CONVOY}`, { waitUntil: 'domcontentloaded' });
}

test.describe('Org-Sitzung beim direkten Aufruf', () => {
	test('die Tracking-Ansicht lädt ihren Marschverband', async ({ page }) => {
		await oeffnen(page);

		await expect(page.locator('.convoy-name')).toHaveText('Verlegung Nord');
		await expect(page.locator('.vehicle-row')).toContainText('Heros 12/19');
		await expect(page.locator('.error-bar')).toHaveCount(0);
	});

	test('jede Datenanfrage nennt die Organisation aus der Adresse', async ({ page }) => {
		const koepfe: (string | null)[] = [];
		page.on('request', (req) => {
			if (req.url().includes(`/api/convoys/${CONVOY}`)) {
				koepfe.push(req.headers()['x-org-slug'] ?? null);
			}
		});

		await oeffnen(page);
		await expect(page.locator('.convoy-name')).toHaveText('Verlegung Nord');

		expect(koepfe.length).toBeGreaterThan(0);
		expect(koepfe.every((k) => k === SLUG)).toBe(true);
	});
});
