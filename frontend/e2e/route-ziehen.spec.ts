import { test, expect, type Page, type Request } from '@playwright/test';
import { CONVOY, ELW, GRUNDLAGE, HLF, KONVOI, MTW, SLUG, ich, mockApi } from './kontextmenue-attrappe';
import { einordnen } from '../src/lib/route/einfuegen';

// Route auf der Karte greifen und auf eine andere Straße ziehen, wie bei
// Google Maps. Die Zusage, die man der Karte nicht ansieht: der neue Wegpunkt
// landet **zwischen** den beiden Wegpunkten, zwischen denen das gegriffene
// Stück lag — hinten angehängt führe der Konvoi bis zum letzten Wegpunkt und
// zurück. Und ohne Ziehen (bloßer Klick) wird nichts angelegt.

// Eine waagerechte Linie: `fitBounds` legt sie in die Mitte der Karte, und
// die Länge geht linear in die x-Achse — so ist ein Punkt auf ihr berechenbar.
const BREITE = 50.6;
const VON = 9.0;
const BIS = 12.5;
const LINIE = Array.from({ length: 36 }, (_, i) => [VON + i * 0.1, BREITE]);
const ROUTE = {
	id: 'r1', convoy_id: CONVOY, distance_m: 250_000, duration_s: 10_800, routing_params: {},
	geojson: { type: 'LineString', coordinates: LINIE }, fuel_analysis: null, kanalwechsel: [],
	durchfahrtshoehen: null, bruecken: null, gewichtsgrenzen: null,
};

const KACHEL = Buffer.from(
	'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64',
);

async function planungMitRoute(page: Page, rolle = 'admin') {
	const aufrufe = await mockApi(page, {
		...GRUNDLAGE,
		'GET /api/auth/me': (req: Request) => ({ ...(ich(req) as object), role: rolle }),
		'GET /api/vehicles/': [HLF, MTW, ELW],
		'GET /api/convoys/': [KONVOI],
		[`GET /api/convoys/${CONVOY}`]: KONVOI,
		[`GET /api/convoys/${CONVOY}/route`]: ROUTE,
		[`POST /api/convoys/${CONVOY}/calculate-route`]: ROUTE,
		'GET /api/organizations/': [],
	});
	// Echte Kacheln statt der 404 aus `mockApi`: scheitern alle, feuert MapLibre
	// `load` nicht, und die Route kommt nie auf die Karte.
	await page.route('**/api/tiles/**', (r) => r.fulfill({ contentType: 'image/png', body: KACHEL }));
	await page.addInitScript((slug) => localStorage.setItem(`cp_tutorial_seen_v1__${slug}`, '1'), SLUG);
	await page.goto(`/o/${SLUG}/plan`, { waitUntil: 'domcontentloaded' });
	await expect(page.locator('.maplibregl-marker', { hasText: 'WP Erfurt' })).toBeAttached();
	return aufrufe;
}

/** Bildschirmpunkt der Linie bei Länge *lon*. */
async function aufDerLinie(page: Page, lon: number) {
	const box = (await page.locator('.map-area .maplibregl-canvas').boundingBox())!;
	const rand = 60; // Polster von `fitRoute`
	return {
		x: box.x + rand + ((lon - VON) / (BIS - VON)) * (box.width - 2 * rand),
		y: box.y + box.height / 2,
	};
}

const zeiger = (page: Page) => page.locator('.map-area .maplibregl-canvas').evaluate((c) => (c as HTMLElement).style.cursor);

/** Über die Linie fahren, bis die Hand erscheint (die Karte fliegt erst noch auf die Route). */
async function greifbar(page: Page, lon: number) {
	const p = await aufDerLinie(page, lon);
	await expect.poll(async () => {
		await page.mouse.move(p.x, p.y + 1);
		await page.mouse.move(p.x, p.y);
		return zeiger(page);
	}, { timeout: 10_000 }).toBe('grab');
	return p;
}

async function ziehe(page: Page, von: { x: number; y: number }, dy: number) {
	await page.mouse.down();
	await page.mouse.move(von.x, von.y + dy / 2, { steps: 4 });
	await page.mouse.move(von.x, von.y + dy, { steps: 4 });
	await page.mouse.up();
}

const angelegt = (aufrufe: Awaited<ReturnType<typeof mockApi>>) =>
	aufrufe.filter((a) => a.methode === 'POST' && a.pfad === `/api/convoys/${CONVOY}/waypoints`);

test('Route zwischen Fulda und Erfurt gezogen: neuer Wegpunkt an zweiter Stelle, danach neu berechnet', async ({ page }) => {
	const aufrufe = await planungMitRoute(page);
	const p = await greifbar(page, 10.4);
	await ziehe(page, p, 90);

	await expect.poll(() => angelegt(aufrufe).length).toBe(1);
	const wp = angelegt(aufrufe)[0].koerper as Record<string, number | string>;
	expect(wp).toMatchObject({ name: 'WP 4', type: 'waypoint', hold_duration_min: 0, order_index: 1 });
	// Losgelassen unterhalb der Linie, also südlich davon.
	expect(wp.lat as number).toBeLessThan(BREITE - 0.05);
	expect(Math.abs((wp.lon as number) - 10.4)).toBeLessThan(0.1);

	await expect.poll(() => aufrufe.some((a) => a.pfad === `/api/convoys/${CONVOY}/calculate-route`)).toBe(true);
	// Eingefügt, nicht umsortiert: der Reorder-Weg platzierte jeden vorgeschlagenen Halt mit.
	expect(aufrufe.some((a) => a.pfad.endsWith('/waypoints/reorder'))).toBe(false);
});

test('Hinter dem letzten Wegpunkt gezogen: ans Ende der Liste', async ({ page }) => {
	const aufrufe = await planungMitRoute(page);
	const p = await greifbar(page, 12.1);
	await ziehe(page, p, -80);
	await expect.poll(() => angelegt(aufrufe).length).toBe(1);
	expect((angelegt(aufrufe)[0].koerper as { order_index: number }).order_index).toBe(3);
});

test('Ein Klick auf die Route legt nichts an, Escape bricht das Ziehen ab', async ({ page }) => {
	const aufrufe = await planungMitRoute(page);
	const p = await greifbar(page, 10.4);
	await page.mouse.down();
	await page.mouse.up();

	await page.mouse.down();
	await page.mouse.move(p.x, p.y + 80, { steps: 4 });
	await page.keyboard.press('Escape');
	await page.mouse.up();

	await page.waitForTimeout(300);
	expect(angelegt(aufrufe)).toHaveLength(0);
});

test('Beobachter können die Route nicht greifen', async ({ page }) => {
	await planungMitRoute(page, 'beobachter');
	const p = await aufDerLinie(page, 10.4);
	await page.waitForTimeout(1500);
	await page.mouse.move(p.x, p.y + 1);
	await page.mouse.move(p.x, p.y);
	expect(await zeiger(page)).not.toBe('grab');
});

// ── Einordnung ohne Karte ───────────────────────────────────────────────

const wp = (lon: number, order_index: number, pending_placement = false) => ({ lat: BREITE, lon, order_index, pending_placement });

test('Einordnung: zwischen den Nachbarn auf der Strecke, nicht nach Listenlänge', () => {
	const liste = [wp(9.5, 0), wp(10.5, 4), wp(11.5, 7)];
	expect(einordnen(LINIE, liste, { lat: BREITE, lon: 9.2 }).order_index).toBe(0);
	expect(einordnen(LINIE, liste, { lat: BREITE, lon: 10.0 })).toEqual({
		order_index: 4, vor: { lat: BREITE, lon: 9.5 }, nach: { lat: BREITE, lon: 10.5 },
	});
	expect(einordnen(LINIE, liste, { lat: BREITE, lon: 12.0 }, null, { lat: 51, lon: 12.5 })).toEqual({
		order_index: 8, vor: { lat: BREITE, lon: 11.5 }, nach: { lat: 51, lon: 12.5 },
	});
});

test('Einordnung: ein wartender Vorschlag am Listenende ist kein Bezugspunkt', () => {
	// Der Tankstopp liegt bei 10.0, steht aber hinten — wer bei 11.0 zieht,
	// gehört hinter WP 10.5, nicht hinter den Vorschlag.
	const liste = [wp(9.5, 0), wp(10.5, 1), wp(12.0, 2), wp(10.0, 3, true)];
	expect(einordnen(LINIE, liste, { lat: BREITE, lon: 11.0 }).order_index).toBe(2);
});

test('Einordnung: eine doppelt befahrene Stichstrecke kehrt die Reihenfolge nicht um', () => {
	// Hin bis 11.0 und auf demselben Weg zurück bis 10.0, dann weiter nach Norden.
	const hin = Array.from({ length: 11 }, (_, i) => [10.0 + i * 0.1, BREITE]);
	const zurueck = [...hin].reverse().slice(1);
	const norden = Array.from({ length: 10 }, (_, i) => [10.0, BREITE + (i + 1) * 0.1]);
	const linie = [...hin, ...zurueck, ...norden];
	// Halt an der Spitze der Stichstrecke, danach ein Punkt im Norden.
	const liste = [wp(11.0, 0), { lat: BREITE + 0.5, lon: 10.0, order_index: 1 }];
	// Gegriffen im Norden: hinter beide, nicht davor.
	expect(einordnen(linie, liste, { lat: BREITE + 0.8, lon: 10.0 }).order_index).toBe(2);
	expect(einordnen(linie, liste, { lat: BREITE + 0.2, lon: 10.0 }).order_index).toBe(1);
});
