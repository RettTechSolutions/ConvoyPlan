import adapter from '@sveltejs/adapter-node';
import { withPwa } from '@vite-pwa/sveltekit';
import { defineConfig } from 'vite';
import { readFileSync } from 'fs';

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
		// `withPwa` ruft `sveltekit()` mit ihr selbst auf (seit @vite-pwa/sveltekit 2.0)
		// und erzeugt den Service Worker im `adapt()` des Adapters, nach beiden
		// Bundles. Die Brücke für SvelteKit 3, die das bis dahin von Hand nachholte,
		// ist damit entfallen.
		...withPwa({
			compilerOptions: {
				// Runes für das Projekt erzwingen, nicht für Bibliotheken. Kann mit Svelte 6 weg.
				runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true),
			},
			adapter: adapter(),
			// SvelteKit 3 kennt `$lib` nicht mehr von selbst (Nachfolger: `#lib`).
			// Der Alias hält die bestehenden Importe gültig.
			alias: { $lib: 'src/lib' },
		}, {
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
			// SvelteKit 3 setzt Vites `base` relativ (`./`); die App liegt aber unter `/`,
			// und der Service Worker gilt für alle Routen (Scope `/`, umfasst `/track`).
			base: '/',
			maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
			// In 1.x `workbox`, seit 2.0 nach der Strategie benannt.
			generateSW: {
				// Das Plugin hängt `prerendered/**` an die Muster an; mit adapter-node wird
				// nichts vorgerendert, das Verzeichnis fehlt. Seit 2.0 bricht ein leeres
				// Muster den Build sonst ab („One of the glob patterns doesn't match").
				globStrict: false,
				// Kein Navigations-Fallback. Steht der Schlüssel nicht da, setzt das Plugin
				// (1.x wie 2.0) `navigateFallback = base`, und Workbox beantwortet *jede*
				// Navigation mit der precachten Seite `/` (bzw. `./`), online wie offline. Die
				// App rendert per SSR, die Seite steht nie im Precache, und
				// `createHandlerBoundToURL` wirft schon beim Auswerten von `sw.js`
				// (`non-precached-url`): Der Service Worker installierte sich nie. Der Schlüssel
				// muss deshalb *vorhanden* sein, mit `undefined`; das Plugin fragt mit `in`.
				// Offline zeigt eine Navigation die Fehlerseite des Browsers. Eine gecachte
				// Seitenhülle zeigte veraltete Sitzungs- und Konvoidaten. Eine geöffnete
				// Tracking-Ansicht läuft weiter; sie braucht nur Kacheln und Chunks.
				navigateFallback: undefined,
				//
				// Precache nur die gehashten Bundles (etwa 3 MB, mit Brotli rund 0,7 MB, einmal
				// je Gerät, danach nur, was sich geändert hat). Gesucht wird ab
				// `.svelte-kit/output`, deshalb die Wurzel `client/`. Logos, Icons und SVGs
				// standen mit 22 MB drin (das alte `globIgnores: ['logo/**']` griff nie); die
				// lädt der Browser, wenn er sie braucht. Alle Bundles statt nur derer für /track:
				// Den Graphen der Chunks aus SvelteKits Ausgabe zu lesen, wäre brüchig, und der
				// größte Brocken (MapLibre) gehört ohnehin dazu. Nutzen: Eine offene Seite
				// findet nach einem Deploy ihre alten Chunks weiter, auch offline.
				globPatterns: ['client/_app/immutable/**/*.{js,css}'],
				// Hält das Plugin davon ab, eigene Muster anzuhängen (`client/*.webmanifest`,
				// `prerendered/**`); die Präfixe streicht seine Transformation ohnehin.
				modifyURLPrefix: { 'client/': '' },
				// Erste Installation: sofort übernehmen, ohne Neuladen. Sonst liefe ein frisch
				// geöffneter Fahrer-Link bis zum nächsten Aufruf ohne Service Worker, und
				// seine vorab geladenen Kacheln kämen im Funkloch nicht an.
				// Updates: kein `skipWaiting`. Der neue Stand wartet, bis alle Seiten der
				// Instanz zu sind; `clientsClaim` greift erst bei dieser Aktivierung. Ein
				// Neuladen mitten im Einsatz gibt es nicht, auch nicht im Nightly-Kanal.
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
		}),
	],
});
