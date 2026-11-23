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
			// SvelteKit 3 setzt Vites `base` relativ (`./`); die App liegt aber unter `/`,
			// und der Service Worker soll für alle Routen gelten (Pfad und Scope in
			// `registerSW.js`). In 1.x hieß das `kit.base` und erzeugte zusätzlich einen
			// Navigations-Fallback auf `/` — den 2.0 ohne `adapterFallback` nicht mehr
			// baut. Gut so: `/` liegt nicht im Precache, der Fallback hätte bei jeder
			// Navigation einen Fehler geworfen.
			base: '/',
			maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
			// In 1.x `workbox`, seit 2.0 nach der Strategie benannt.
			generateSW: {
				// Das Plugin hängt `prerendered/**` an die Muster an; mit adapter-node wird
				// nichts vorgerendert, das Verzeichnis fehlt. Seit 2.0 bricht ein leeres
				// Muster den Build sonst ab („One of the glob patterns doesn't match").
				globStrict: false,
				// Gesucht wird ab `.svelte-kit/output`, also in `client/` UND `server/`;
				// ohne die Wurzel `client/` stünde jedes Asset doppelt im Precache.
				// Das Muster bildet den Stand von 1.x nach (132 Einträge). Das frühere
				// `globIgnores: ['logo/**', 'icons/**']` hat nie gegriffen, weil die
				// Pfade mit `client/` beginnen — Logos und Icons waren immer dabei.
				globPatterns: ['client/**/*.{js,css,ico,png,svg,webp,webmanifest}'],
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
