import { test, expect, type Page } from '@playwright/test';
import { blockExternal, mockTrack } from './fixtures';

// Der Service Worker ist das, was die Offline-Kacheln trägt. `tileCache.ts` legt den
// Kachelkorridor einer Route in den Cache `osm-tiles`; ausliefern kann ihn nur ein
// Service Worker. Bis 2026-11 wurde `sw.js` gebaut, aber nie angemeldet, und niemand
// bemerkte es: Die Karte sah online genauso aus.
//
// Überall sonst ist er blockiert (`playwright.config.ts`), hier ausdrücklich erlaubt.
test.use({ serviceWorkers: 'allow' });

const SLUG = 'Sw0rkr12';
// 1×1-PNG. Der Inhalt zählt nur als Wiedererkennung: Offline muss genau er zurückkommen.
const PNG = Buffer.from(
	'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYPj/HwADAgH/kn0WawAAAABJRU5ErkJggg==',
	'base64',
);
const KACHEL = '/api/tiles/12/2178/1408.png';

/** Wartet, bis der Service Worker die Seite steuert: ohne Neuladen, über `clientsClaim`. */
async function gesteuert(page: Page) {
	await page.waitForFunction(() => navigator.serviceWorker.controller !== null, null, { timeout: 30_000 });
}

/** Holt eine Kachel aus der Seite heraus und gibt Status und Bytes zurück (Fehler = Status 0). */
async function holen(page: Page, url: string) {
	return page.evaluate(async (u) => {
		try {
			const r = await fetch(u);
			return { status: r.status, bytes: Array.from(new Uint8Array(await r.arrayBuffer())) };
		} catch {
			return { status: 0, bytes: [] as number[] };
		}
	}, url);
}

for (const pfad of ['/', '/track', `/track/${SLUG}`]) {
	test(`auf ${pfad} ist der Service Worker mit Scope "/" angemeldet und steuert die Seite`, async ({ page }) => {
		await blockExternal(page);
		await mockTrack(page, { scope: 'driver' });
		await page.goto(pfad, { waitUntil: 'domcontentloaded' });

		await gesteuert(page);
		const reg = await page.evaluate(async () => {
			const r = await navigator.serviceWorker.getRegistration();
			return { scope: r?.scope, skript: r?.active?.scriptURL };
		});
		expect(reg).toEqual({ scope: 'http://localhost:4173/', skript: 'http://localhost:4173/sw.js' });
	});
}

test('der Precache hält nur die gehashten Bundles, keine Logos und keine Seiten', async ({ request }) => {
	const sw = await (await request.get('/sw.js')).text();
	// Das Format wechselt mit der Workbox-Fassung (1.x: "…", 2.0: `…`).
	const urls = [...sw.matchAll(/url:\s*["'`]([^"'`]+)["'`]/g)].map((m) => m[1]);
	expect(urls.length).toBeGreaterThan(0);
	// Bilder lädt der Browser, wenn er sie braucht. Mit den Logos lag der Precache bei 27 MB.
	expect(urls.filter((u) => !u.startsWith('_app/immutable/'))).toEqual([]);
	// Kein Neuladen mitten im Einsatz: Ein neuer Stand wartet, bis alle Seiten zu sind.
	// Übrig bleibt nur der Nachrichten-Haken von Workbox, und den ruft niemand.
	const ohneNachricht = sw.replace(/SKIP_WAITING[^&]*&&\s*self\.skipWaiting\(\)/, '');
	expect(ohneNachricht).not.toContain('skipWaiting()');
});

test('eine Navigation beantwortet der Server, nicht der Service Worker', async ({ page }) => {
	// Ein Navigations-Fallback (das Plugin setzt ihn ohne `navigateFallback` von selbst)
	// beantwortete jede Navigation mit einer precachten Seite, und die gibt es unter SSR
	// nicht. Geprüft am Verhalten: Die Namen im gebauten `sw.js` sind minifiziert.
	await blockExternal(page);
	await mockTrack(page, { scope: 'driver' });
	await page.goto('/', { waitUntil: 'domcontentloaded' });
	await gesteuert(page);
	const antwort = await page.goto(`/track/${SLUG}`, { waitUntil: 'domcontentloaded' });
	expect(antwort?.fromServiceWorker()).toBe(false);
	expect(antwort?.status()).toBe(200);
});

test('eine vorab geladene Kachel kommt im Funkloch aus "osm-tiles"', async ({ page, context }) => {
	await blockExternal(page);
	await mockTrack(page, { scope: 'driver' });
	await page.goto(`/track/${SLUG}`, { waitUntil: 'domcontentloaded' });
	await gesteuert(page);

	// Genau das tut `tileCache.ts`: Es schreibt den Korridor direkt in den Cache.
	await page.evaluate(
		async ({ url, bytes }) => {
			const cache = await caches.open('osm-tiles');
			await cache.put(url, new Response(new Uint8Array(bytes), { headers: { 'Content-Type': 'image/png' } }));
		},
		{ url: KACHEL, bytes: Array.from(PNG) },
	);

	// Offline, und falls doch etwas hinausginge: abbrechen.
	await context.route('**/api/tiles/**', (r) => r.abort('internetdisconnected'));
	await context.setOffline(true);

	const antwort = await holen(page, KACHEL);
	expect(antwort.status).toBe(200);
	expect(antwort.bytes).toEqual(Array.from(PNG));

	// Gegenprobe: Eine Kachel, die nicht im Cache liegt, kommt offline nicht.
	expect((await holen(page, '/api/tiles/12/2179/1408.png')).status).toBe(0);
});

test('eine einmal angezeigte Kachel landet in "osm-tiles" und kommt offline wieder', async ({ page, context }) => {
	await blockExternal(page);
	await mockTrack(page, { scope: 'driver' });
	let ausDemNetz = 0;
	// Die Anfrage stellt der Service Worker, nicht die Seite; `page.route` sähe sie nicht.
	await context.route('**/api/tiles/**', async (r) => {
		ausDemNetz++;
		await r.fulfill({ body: PNG, contentType: 'image/png' });
	});
	await page.goto(`/track/${SLUG}`, { waitUntil: 'domcontentloaded' });
	await gesteuert(page);

	expect((await holen(page, KACHEL)).status).toBe(200);
	// StaleWhileRevalidate legt die Antwort nach dem Ausliefern in den Cache.
	await expect
		.poll(() => page.evaluate(async (u) => !!(await (await caches.open('osm-tiles')).match(u)), KACHEL))
		.toBe(true);
	const vorher = ausDemNetz;

	await context.unroute('**/api/tiles/**');
	await context.route('**/api/tiles/**', (r) => r.abort('internetdisconnected'));
	await context.setOffline(true);

	const antwort = await holen(page, KACHEL);
	expect(antwort.status).toBe(200);
	expect(antwort.bytes).toEqual(Array.from(PNG));
	expect(vorher).toBeGreaterThan(0);
});
