import { expect, test } from '@playwright/test';
import { blockExternal } from './fixtures';

/**
 * Der Service Worker trägt die Offline-Kacheln: `$lib/tracking/tileCache.ts`
 * legt den Korridor einer Route vorab in den Cache `osm-tiles`, ausliefern
 * kann ihn im Funkloch nur der Service Worker. Bis 2026-11 wurde er gebaut,
 * aber nirgends angemeldet — die Zusage "Kacheln lassen sich für den
 * Offline-Betrieb vorladen" (Wiki, Live-Tracking) war ohne Wirkung, und man
 * sah es keinem Bildschirmfoto an.
 *
 * Alle anderen Specs blockieren den Service Worker (playwright.config.ts);
 * dieser lässt ihn zu.
 */
test.use({ serviceWorkers: 'allow' });

/** Ein 1×1-PNG, wie es der Kachel-Proxy unter /api/tiles liefert. */
const PNG = Buffer.from(
	'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
	'base64',
);

async function bereit(page: import('@playwright/test').Page) {
	await blockExternal(page);
	await page.goto('/');
	// Angemeldet wird im onMount des Wurzel-Layouts; `ready` wartet auf die
	// Aktivierung, `controller` auf die Übernahme der offenen Seite.
	return page.evaluate(async () => {
		const reg = await navigator.serviceWorker.ready;
		if (!navigator.serviceWorker.controller) {
			await new Promise<void>((fertig) =>
				navigator.serviceWorker.addEventListener('controllerchange', () => fertig(), { once: true }),
			);
		}
		return { scope: reg.scope, skript: reg.active?.scriptURL ?? '' };
	});
}

test('der Service Worker ist angemeldet, gilt für alle Routen und übernimmt die Seite sofort', async ({ page, baseURL }) => {
	const { scope, skript } = await bereit(page);
	expect(scope).toBe(`${baseURL}/`);
	expect(skript).toBe(`${baseURL}/sw.js`);
	// /track liegt im Scope: der Fahrer-Link ist dieselbe Origin, derselbe Worker.
	expect(new URL('/track/beispiel', baseURL).href.startsWith(scope)).toBe(true);
	// Übernahme ohne Neuladen (`clientsClaim`): sonst griffe ein eben vorgeladener
	// Korridor erst nach dem nächsten Seitenaufruf.
	expect(await page.evaluate(() => navigator.serviceWorker.controller?.scriptURL)).toBe(`${baseURL}/sw.js`);
});

test('eine vorab abgelegte Kachel kommt offline aus dem Cache', async ({ page, context }) => {
	await bereit(page);
	const kachel = '/api/tiles/12/2200/1343.png';

	// Wie tileCache.ts: direkt in den benannten Cache, ohne Netz.
	await page.evaluate(
		async ({ url, bytes }) => {
			const cache = await caches.open('osm-tiles');
			await cache.put(url, new Response(new Uint8Array(bytes), { headers: { 'Content-Type': 'image/png' } }));
		},
		{ url: kachel, bytes: [...PNG] },
	);

	await context.setOffline(true);
	const antwort = await page.evaluate(async (url) => {
		const r = await fetch(url);
		return { status: r.status, typ: r.headers.get('content-type'), laenge: (await r.arrayBuffer()).byteLength };
	}, kachel);
	expect(antwort).toEqual({ status: 200, typ: 'image/png', laenge: PNG.length });

	// Gegenprobe: eine Kachel, die nicht im Cache liegt, scheitert offline —
	// sonst bewiese der Test oben nichts über den Cache.
	const fehlt = await page.evaluate(async () => {
		try {
			await fetch('/api/tiles/12/9999/9999.png');
			return 'geladen';
		} catch {
			return 'gescheitert';
		}
	});
	expect(fehlt).toBe('gescheitert');
});

test('Logos und App-Icons liegen nicht im Precache, der Code der App schon', async ({ page }) => {
	await bereit(page);
	const urls = await page.evaluate(async () => {
		const namen = await caches.keys();
		const precache = namen.find((n) => n.startsWith('workbox-precache'));
		if (!precache) return [];
		const cache = await caches.open(precache);
		return (await cache.keys()).map((r) => new URL(r.url).pathname);
	});
	expect(urls.length).toBeGreaterThan(50);
	expect(urls.some((u) => u.startsWith('/_app/immutable/'))).toBe(true);
	expect(urls.filter((u) => u.startsWith('/logo/') || u.startsWith('/icons/'))).toEqual([]);
});

test('eine einmal angezeigte Kachel landet in "osm-tiles" und kommt offline wieder', async ({ page, context }) => {
	// Der zweite Weg in den Cache neben tileCache.ts: StaleWhileRevalidate legt jede
	// Kachel ab, die die Karte online holt. Daran hängt, dass auch der Ausschnitt
	// neben dem vorgeladenen Korridor im Funkloch stehen bleibt.
	await bereit(page);
	const kachel = '/api/tiles/12/2201/1343.png';
	let ausDemNetz = 0;
	// Die Anfrage stellt der Service Worker, nicht die Seite: `page.route` sähe sie nicht.
	await context.route('**/api/tiles/**', async (route) => {
		ausDemNetz++;
		await route.fulfill({ body: PNG, contentType: 'image/png' });
	});

	expect(await page.evaluate(async (url) => (await fetch(url)).status, kachel)).toBe(200);
	expect(ausDemNetz).toBe(1);
	// Abgelegt wird nach dem Ausliefern; darauf warten, nicht raten.
	await expect
		.poll(() => page.evaluate(async (url) => !!(await (await caches.open('osm-tiles')).match(url)), kachel))
		.toBe(true);

	await context.unroute('**/api/tiles/**');
	await context.route('**/api/tiles/**', (route) => route.abort('internetdisconnected'));
	await context.setOffline(true);
	const antwort = await page.evaluate(async (url) => {
		const r = await fetch(url);
		return { status: r.status, laenge: (await r.arrayBuffer()).byteLength };
	}, kachel);
	expect(antwort).toEqual({ status: 200, laenge: PNG.length });
});

test('eine Navigation beantwortet der Server, nicht der Service Worker', async ({ page }) => {
	// Ohne `navigateFallback: null` baut das Plugin einen Navigations-Fallback auf die
	// Basis, und Workbox beantwortete jede Navigation mit einer precachten Seite, die es
	// unter SSR nicht gibt. Geprüft am Verhalten: die Namen in `sw.js` sind minifiziert,
	// eine Suche nach "NavigationRoute" bestünde immer.
	await bereit(page);
	const antwort = await page.goto('/status');
	expect(antwort?.fromServiceWorker()).toBe(false);
	expect(antwort?.status()).toBe(200);
});
