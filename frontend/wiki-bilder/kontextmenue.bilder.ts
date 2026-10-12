import { test, expect, type Locator, type Page } from '@playwright/test';
import { fileURLToPath } from 'node:url';
import { adminBereich, menue, orgAdmin, planung, tab } from '../e2e/kontextmenue-attrappe';

// Bilder zum Abschnitt „Kontextmenü" in `wiki/Benutzerhandbuch.md`.
// Erzeugt mit `npm run wiki:bilder` (siehe `playwright.wiki.config.ts`).

const ZIEL = fileURLToPath(new URL('../../wiki/bilder/', import.meta.url));

/**
 * Echte Kartenkacheln statt der grauen Fläche aus den Tests. Wenige Dutzend
 * Kacheln je Lauf, mit Kennung — im Rahmen der OSM-Nutzungsregeln; die
 * Namensnennung steht auf jedem Bild in der Karte.
 */
const kacheln = new Map<string, Buffer>();
async function osmKacheln(page: Page) {
	await page.route('**/api/tiles/**', async (route) => {
		const pfad = new URL(route.request().url()).pathname.replace('/api/tiles/', '');
		let bild = kacheln.get(pfad);
		if (!bild) {
			const antwort = await route.fetch({
				url: `https://tile.openstreetmap.org/${pfad}`,
				headers: { 'User-Agent': 'ConvoyPlan-Wiki-Bilder (https://github.com/RettTechSolutions/ConvoyPlan)' },
			});
			bild = await antwort.body();
			kacheln.set(pfad, bild);
		}
		await route.fulfill({ body: bild, contentType: 'image/png' });
	});
}

/** Ausschnitt um die genannten Elemente, mit etwas Rand — begrenzt aufs Fenster. */
async function ausschnitt(page: Page, elemente: Locator[], rand = 20) {
	const boxen = await Promise.all(elemente.map(async (e) => (await e.boundingBox())!));
	const v = page.viewportSize()!;
	const x = Math.max(0, Math.min(...boxen.map((b) => b.x)) - rand);
	const y = Math.max(0, Math.min(...boxen.map((b) => b.y)) - rand);
	const r = Math.min(v.width, Math.max(...boxen.map((b) => b.x + b.width)) + rand);
	const u = Math.min(v.height, Math.max(...boxen.map((b) => b.y + b.height)) + rand);
	return { x, y, width: r - x, height: u - y };
}

/**
 * PNG für Oberfläche, JPEG für die Karte: ein ganzes Fenster voller Kacheln
 * wäre als PNG mehrere Megabyte groß.
 */
async function bild(page: Page, datei: string, clip?: { x: number; y: number; width: number; height: number }) {
	// Der Mauszeiger steht sonst auf einem Eintrag und färbt ihn ein.
	await page.mouse.move(1, 1);
	const jpeg = datei.endsWith('.jpg');
	await page.screenshot({ path: `${ZIEL}${datei}`, clip, animations: 'disabled', type: jpeg ? 'jpeg' : 'png', quality: jpeg ? 80 : undefined });
}

/** Warten, bis die Kacheln im Bild da sind — sonst halbe Karte. */
async function karteGeladen(page: Page) {
	await page.waitForFunction(() => {
		const tiles = performance.getEntriesByType('resource').filter((r) => r.name.includes('/api/tiles/'));
		return tiles.length > 8;
	});
	await page.waitForLoadState('networkidle');
}

test('Karte der Planung', async ({ page }) => {
	await planung(page);
	await osmKacheln(page);
	await page.reload({ waitUntil: 'domcontentloaded' });
	await karteGeladen(page);

	const karte = page.locator('.map-area .maplibregl-canvas');
	const box = (await karte.boundingBox())!;
	await karte.click({ button: 'right', position: { x: box.width * 0.42, y: box.height * 0.32 } });
	await expect(menue(page)).toBeVisible();
	// Ganzes Fenster: die Leiste links gehört aufs Bild, damit man sieht, wo man ist.
	await bild(page, 'kontextmenue-karte.jpg');
});

test('Wegpunktliste', async ({ page }) => {
	await planung(page);
	await osmKacheln(page);
	await page.reload({ waitUntil: 'domcontentloaded' });
	await tab(page, 'Wegpunkte').click();
	const zeile = page.locator('.wp-item', { hasText: 'WP Erfurt' });
	await zeile.click({ button: 'right', position: { x: 60, y: 10 } });
	await expect(menue(page)).toBeVisible();
	await bild(page, 'kontextmenue-wegpunkte.png', await ausschnitt(page, [page.locator('#sidebar .tab-content'), menue(page)]));
});

test('Mitglieder im Org-Admin', async ({ page }) => {
	await orgAdmin(page);
	await page.getByRole('cell', { name: 'anna@example.org' }).click({ button: 'right' });
	await expect(menue(page)).toBeVisible();
	await bild(page, 'kontextmenue-mitglieder.png', await ausschnitt(page, [page.locator('table.user-table'), menue(page)]));
});

test('Benutzer im Admin-Bereich', async ({ page }) => {
	await adminBereich(page);
	// Anna ist aktiv: das Häkchen am Schalter zeigt, dass das Menü den Stand kennt.
	await page.getByRole('cell', { name: 'anna@example.org' }).click({ button: 'right' });
	await expect(menue(page)).toBeVisible();
	await bild(page, 'kontextmenue-benutzer.png', await ausschnitt(page, [page.locator('table').filter({ hasText: 'anna@example.org' }), menue(page)]));
});
