import { expect, test } from '@playwright/test';
import { blockExternal, trackPayload } from './fixtures';

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

test('übernimmt ein neuer Service Worker, lädt die offene Seite nicht neu', async ({ page, baseURL }) => {
	// Die Hülle aus `virtual:pwa-register` lädt im Modus `prompt` die Seite neu, sobald ein
	// wartender Worker übernimmt — in jedem offenen Tab, auch im Fahrer-Link. Heute ruft
	// niemand `skipWaiting`; dieser Test tut es, wie es ein künftiger Update-Knopf täte,
	// und verlangt, dass `onNeedReload` in `$lib/pwa/serviceWorker.ts` das Neuladen abfängt.
	await bereit(page);
	// Neu laden heißt hier: Die Hülle meldet sich an, während die Seite schon gesteuert ist.
	// Nur dann hält sie die Übernahme für ein Update und lädt neu; das ist jeder Aufruf
	// nach dem ersten.
	await page.reload();
	await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
	// Der Hülle Zeit geben, sich anzumelden (onMount, dynamischer Import).
	await page.waitForTimeout(500);

	let navigationen = 0;
	page.on('framenavigated', (rahmen) => {
		if (rahmen === page.mainFrame()) navigationen++;
	});
	await page.evaluate(() => {
		(window as unknown as { __marke: string }).__marke = 'vor dem Update';
	});

	// Ein neuer Stand. Das Skript des Service Workers holt der Browser an `context.route`
	// vorbei; eine andere Adresse im selben Scope erzwingt die Installation trotzdem.
	await page.evaluate(async () => {
		const reg = await navigator.serviceWorker.register('/sw.js?stand=2', { scope: '/' });
		const neu = reg.installing ?? reg.waiting;
		if (!neu) throw new Error('kein neuer Service Worker');
		if (neu.state !== 'installed') {
			await new Promise<void>((fertig) =>
				neu.addEventListener('statechange', () => neu.state === 'installed' && fertig()),
			);
		}
		const uebernommen = new Promise<void>((fertig) =>
			navigator.serviceWorker.addEventListener('controllerchange', () => fertig(), { once: true }),
		);
		// Was ein Update-Knopf über `updateServiceWorker()` täte.
		neu.postMessage({ type: 'SKIP_WAITING' });
		await uebernommen;
	});

	// Ein Neuladen setzte direkt im `controlling`-Handler ein; eine Sekunde Spielraum.
	await page.waitForTimeout(1000);
	expect(navigationen).toBe(0);
	expect(await page.evaluate(() => (window as unknown as { __marke?: string }).__marke)).toBe('vor dem Update');
	// Gegenprobe, dass die Übernahme wirklich stattfand.
	expect(await page.evaluate(() => navigator.serviceWorker.controller?.scriptURL)).toBe(`${baseURL}/sw.js?stand=2`);
});

// ── Fahrer-Link: der Korridor der Route liegt vorab im Cache ─────────────────
//
// Bis 2026-11 lud nur die angemeldete Tracking-Ansicht den Korridor vor. Der
// Fahrer-Link hatte offline nur die Übersicht, die er gerade zeigte; beim
// Hineinzoomen gab es nichts als hochgezogene Übersichtskacheln. Vorgeladen wird
// nur mit Fahrerrechten (`driver`): ein Lese-Link sitzt selten im Fahrzeug, und
// das Vorladen kostet Mobilfunkvolumen.

/** Rund 10 km Route, damit der Korridor klein bleibt und der Test schnell. */
const ROUTE = Array.from({ length: 10 }, (_, i) => [11.58 - 0.009 * i, 48.14 + 0.007 * i]);

function kachelVon(lon: number, lat: number, z: number) {
	const r = (lat * Math.PI) / 180;
	const x = Math.floor(((lon + 180) / 360) * 2 ** z);
	const y = Math.floor(((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 2 ** z);
	return `/api/tiles/${z}/${x}/${y}.png`;
}

async function linkMitRoute(page: import('@playwright/test').Page, context: import('@playwright/test').BrowserContext, scope: 'track' | 'driver') {
	const geholt = { config: 0 };
	// Kachelanfragen stellt teils der Service Worker; `context.route` sieht beide.
	await context.route('**/api/tiles/config', async (route) => {
		geholt.config++;
		await route.fulfill({ json: { prefetch: { zooms: [12, 13, 14], max_tiles: 1500 } } });
	});
	await context.route(/\/api\/tiles\/\d+\/\d+\/\d+\.png$/, async (route) => {
		await route.fulfill({ body: PNG, contentType: 'image/png' });
	});
	await blockExternal(page);
	await page.route('**/api/track/*', (route) =>
		route.fulfill({ json: { ...trackPayload(scope), geojson: { type: 'LineString', coordinates: ROUTE } } }),
	);
	await page.goto(`/track/${SLUG_ROUTE}`, { waitUntil: 'domcontentloaded' });
	await page.waitForFunction(() => navigator.serviceWorker.controller !== null, null, { timeout: 30_000 });
	return geholt;
}

const SLUG_ROUTE = 'R0uteVor';

/** Anzahl der Kacheln je Zoomstufe im Cache `osm-tiles`. */
function imCache(page: import('@playwright/test').Page) {
	return page.evaluate(async () => {
		const z: Record<string, number> = {};
		for (const k of await (await caches.open('osm-tiles')).keys()) {
			const n = new URL(k.url).pathname.split('/')[3];
			z[n] = (z[n] ?? 0) + 1;
		}
		return z;
	});
}

test('der Fahrer-Link lädt den Korridor der Route vor, und eine Detailkachel kommt im Funkloch', async ({ page, context }) => {
	const geholt = await linkMitRoute(page, context, 'driver');
	const mitte = ROUTE[5];
	// Zoom 14 ist die letzte Stufe, die vorgeladen wird; liegt ihre Kachel aus der Mitte
	// der Route im Cache, sind 12 und 13 schon durch.
	const detail = kachelVon(mitte[0], mitte[1], 14);

	await expect
		.poll(() => page.evaluate(async (u) => !!(await (await caches.open('osm-tiles')).match(u)), detail), { timeout: 30_000 })
		.toBe(true);
	expect(geholt.config).toBe(1);
	const z = await imCache(page);
	for (const stufe of ['12', '13', '14']) expect(z[stufe], `Zoomstufe ${stufe}`).toBeGreaterThan(0);

	// Funkloch: Die Detailkachel kommt aus dem Cache.
	await context.unroute(/\/api\/tiles\/\d+\/\d+\/\d+\.png$/);
	await context.route('**/api/tiles/**', (route) => route.abort('internetdisconnected'));
	await context.setOffline(true);
	const antwort = await page.evaluate(async (u) => {
		const r = await fetch(u);
		return { status: r.status, laenge: (await r.arrayBuffer()).byteLength };
	}, detail);
	expect(antwort).toEqual({ status: 200, laenge: PNG.length });
});

test('ein reiner Lese-Link lädt nichts vor', async ({ page, context }) => {
	const geholt = await linkMitRoute(page, context, 'track');
	// Jedes Vorladen fragt zuerst `/api/tiles/config` ab, sonst tut das niemand. Nach
	// Kacheln ab Zoom 12 zu fragen, ginge nicht: Eine 10-km-Route zeigt die Karte selbst
	// schon so nah. Zeit lassen, die ein Vorladen bräuchte, um anzufangen.
	await expect(page.locator('.maplibregl-canvas').first()).toBeVisible();
	await page.waitForTimeout(3_000);
	expect(geholt.config).toBe(0);
});
