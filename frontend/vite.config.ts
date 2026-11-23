import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { SvelteKitPWA } from '@vite-pwa/sveltekit';
import { defineConfig, type Plugin, type PluginOption, type ResolvedConfig } from 'vite';
import { existsSync, readFileSync } from 'fs';

const pkg = JSON.parse(readFileSync('package.json', 'utf-8'));
const gitSha = process.env.GIT_SHA?.slice(0, 7);
// APP_VERSION is injected at image build time from the git tag (see Dockerfile
// / release workflow); fall back to package.json for local dev builds.
const baseVersion = (process.env.APP_VERSION?.trim() || pkg.version).replace(/^v/, '');
// `git describe` already embeds the commit ("-g<sha>") for builds ahead of the
// last tag; only append the short sha when it isn't already part of the string,
// so the footer shows it exactly once.
const hasCommit = /[-+]g?[0-9a-f]{7,}/i.test(baseVersion);
const appVersion = gitSha && !hasCommit ? `${baseVersion}+${gitSha}` : baseVersion;

/**
 * Brücke zwischen `@vite-pwa/sveltekit` (für SvelteKit 2 geschrieben) und SvelteKit 3.
 *
 * Das Plugin erzeugt den Service Worker im `closeBundle` des SSR-Builds und erkennt
 * den an `build.ssr` der Vite-Konfiguration. SvelteKit 3 baut Client und Server
 * über die Environment-API in *einem* Durchgang, die Bedingung wird nie wahr — und
 * ohne Fehlermeldung fehlte `sw.js` im Build und mit ihm die Offline-Kacheln.
 *
 * SvelteKit ruft den Adapter in einem `buildApp`-Haken mit `order: 'post'` auf,
 * ausdrücklich nach den `buildApp`-Haken anderer Plugins. Dazwischen liegen beide
 * Bundles in `.svelte-kit/output`, und hier lässt sich der Schritt nachholen, den
 * das Plugin sonst selbst getan hätte. Fällt weg, sobald `@vite-pwa/sveltekit`
 * SvelteKit 3 unterstützt.
 */
function pwaFuerSvelteKit3(plugins: PluginOption[]): PluginOption[] {
	const build = (plugins as Plugin[]).find((p) => p?.name === 'vite-plugin-pwa:sveltekit:build');
	if (!build) throw new Error('@vite-pwa/sveltekit: Build-Plugin nicht gefunden');
	const closeBundle = build.closeBundle as { handler: () => Promise<void> };
	const generateBundle = build.generateBundle as (this: unknown, ...args: unknown[]) => Promise<void>;
	let root = '';
	return [
		...(plugins as Plugin[]).filter((p) => p !== build).map((p) =>
			p?.name !== 'vite-plugin-pwa'
				? p
				: {
						...p,
						// `sw.js` landet unter `build.outDir` und wird von dort in den Client
						// kopiert. SvelteKit 3 setzt das Ziel des SSR-Builds nur noch an dessen
						// Environment; oben stünde `dist`.
						configResolved(config: ResolvedConfig) {
							const outDir = config.environments.ssr.build.outDir;
							return (p.configResolved as (c: unknown) => unknown)({ ...config, build: { ...config.build, outDir } });
						},
					},
		),
		{
			...build,
			// Nicht `pre` wie das Original: Der eigene `buildApp` muss nach dem von
			// SvelteKit laufen, der `.svelte-kit/output` zu Beginn leert.
			enforce: undefined,
			configResolved(config) {
				root = config.root;
				// `build.ssr` fest auf wahr: `closeBundle` arbeitet nur dann, wir rufen es selbst.
				(build.configResolved as (c: unknown) => void)({ root, build: { ssr: true } });
			},
			// `registerSW.js` gehört nur in den Client-Build, nicht zusätzlich in den Server.
			async generateBundle(...args) {
				if (this.environment.config.consumer !== 'client') return;
				(build.configResolved as (c: unknown) => void)({ root, build: { ssr: false } });
				try {
					await generateBundle.apply(this, args);
				} finally {
					(build.configResolved as (c: unknown) => void)({ root, build: { ssr: true } });
				}
			},
			writeBundle: undefined,
			closeBundle: undefined,
			async buildApp() {
				await closeBundle.handler();
				// Lieber ein roter Build als ein stiller: so fiel das Fehlen zuerst nicht auf.
				const sw = `${root}/.svelte-kit/output/client/sw.js`;
				if (!existsSync(sw)) throw new Error(`Service Worker fehlt: ${sw}`);
			},
		},
	];
}

export default defineConfig({
	define: {
		__APP_VERSION__: JSON.stringify(appVersion),
	},
	// MapLibre startet seinen Worker als Modul-Worker (`new Worker(url,
	// { type: 'module' })`). Vite bündelt Worker sonst als IIFE — der von
	// `$lib/map/maplibre` vorgegebene Worker muss deshalb ESM sein.
	worker: {
		format: 'es',
	},
	plugins: [
		// SvelteKit 3 liest keine `svelte.config.js` mehr; die Konfiguration steht hier.
		sveltekit({
			compilerOptions: {
				// Runes für das Projekt erzwingen, nicht für Bibliotheken. Kann mit Svelte 6 weg.
				runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true),
			},
			adapter: adapter(),
			// SvelteKit 3 kennt `$lib` nicht mehr von selbst (Nachfolger: `#lib`).
			// Der Alias hält die bestehenden Importe gültig.
			alias: { $lib: 'src/lib' },
		}),
		pwaFuerSvelteKit3(SvelteKitPWA({
			// Manifest bewusst abgeschaltet: Das Plugin würde sonst ein drittes
			// Manifest (Name "ConvoyPlan", scope "/") generieren UND dessen
			// <link rel="manifest"> auf JEDER Route automatisch in den <head>
			// injizieren — auch auf /track. Dieses scope-"/"-Manifest umschließt
			// den /track-Bereich und kollidiert mit der eigenständigen
			// Tracking-App, sodass sich Haupt-App und Tracking-App beim
			// Installieren gegenseitig überschreiben.
			//
			// Stattdessen sind die beiden handgepflegten statischen Manifeste die
			// alleinige Quelle der Wahrheit — pro Route umgeschaltet:
			//   - static/app.webmanifest      (id/scope "/")     → ConvoyPlan
			//   - static/tracking.webmanifest (id/scope "/track") → Convoy Tracking
			// (siehe +layout.svelte und TrackingPwaHead.svelte).
			// Das Plugin erzeugt/registriert hier nur noch den Service Worker.
			manifest: false,
			// Angemeldet wird in `$lib/pwa/serviceWorker.ts`, ohne die Workbox-Hülle des
			// Plugins (die lädt die Seite bei einem Update neu). `registerSW.js` braucht
			// es deshalb nicht.
			injectRegister: false,
			// SvelteKit 3 setzt Vites `base` relativ (`./`). Die App liegt unter `/`.
			kit: { base: '/' },
			workbox: {
				// Kein Navigations-Fallback. Das Plugin setzt sonst `navigateFallback = base`,
				// und Workbox beantwortet dann *jede* Navigation mit der precachten Seite `/`,
				// online wie offline. Die App rendert per SSR, `/` steht gar nicht im Precache,
				// und `createHandlerBoundToURL('/')` wirft schon beim Auswerten von `sw.js`
				// (`non-precached-url`). So hätte sich der Service Worker nie installiert.
				// Offline zeigt eine Navigation deshalb die Fehlerseite des Browsers. Eine
				// gecachte Seitenhülle zeigte veraltete Sitzungs- und Konvoidaten. Eine bereits
				// geöffnete Tracking-Ansicht läuft weiter; sie braucht nur Kacheln und Chunks.
				navigateFallback: null,
				// Nur die gehashten Bundles. Logos, Icons und SVGs standen mit 22 MB im
				// Precache: `globIgnores: ['logo/**']` griff nie, weil die Pfade hier mit
				// `client/` beginnen. Die Bilder lädt der Browser ohnehin, wenn er sie braucht.
				// Die Bundles sind etwa 3 MB, mit Brotli rund 0,7 MB über die Leitung,
				// einmal je Gerät und danach nur, was sich geändert hat. Alle statt nur
				// derer für /track: Den Graphen der Chunks aus SvelteKits Ausgabe
				// herauszulesen, wäre brüchig, und der größte Brocken (MapLibre) gehört
				// ohnehin zu /track. Nutzen offline: nachgeladene Teile einer offenen Seite.
				// Nutzen bei einem Deploy: Eine offene Seite findet ihre alten Chunks
				// weiter, obwohl der Server sie nicht mehr hat.
				// `modifyURLPrefix` hält das Plugin davon ab, eigene Muster anzuhängen
				// (`client/**/*.{png,svg,…}`, `*.webmanifest`).
				globPatterns: ['client/_app/immutable/**/*.{js,css}'],
				modifyURLPrefix: { 'client/': '' },
				maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
				// Erste Installation: sofort übernehmen, ohne Neuladen. Sonst liefe ein
				// frisch geöffneter Fahrer-Link bis zum nächsten Aufruf ohne Service Worker,
				// und seine vorab geladenen Kacheln kämen im Funkloch nicht an.
				// Updates: kein `skipWaiting`. Der neue Stand wartet, bis alle Seiten der
				// Instanz zu sind; `clientsClaim` greift erst bei dieser Aktivierung. Ein
				// Neuladen mitten im Einsatz gibt es also nicht, auch nicht im Nightly-Kanal.
				clientsClaim: true,
				skipWaiting: false,
				runtimeCaching: [
					{
						// Cache map tiles as they are viewed so the map keeps rendering
						// offline (poor signal). StaleWhileRevalidate serves the cached
						// tile immediately and falls back to it when the network fails.
						// The budget is large enough to hold a whole route corridor that
						// is proactively prefetched (see lib/tracking/tileCache.ts) plus
						// the tiles viewed around it, without evicting the route again.
						// Kacheln über den Proxy der eigenen Instanz (/api/tiles).
						urlPattern: /\/api\/tiles\/\d+\/\d+\/\d+\.png$/,
						handler: 'StaleWhileRevalidate',
						options: { cacheName: 'osm-tiles', expiration: { maxEntries: 9000, maxAgeSeconds: 60 * 60 * 24 * 30 } },
					},
				],
			},
		})),
	],
});
