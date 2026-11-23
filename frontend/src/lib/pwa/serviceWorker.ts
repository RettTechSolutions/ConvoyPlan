/**
 * Meldet den Service Worker an, den `@vite-pwa/sveltekit` als `/sw.js` baut.
 *
 * Unter SvelteKit registriert er sich nicht selbst. Bis 2026-11 tat es auch sonst
 * niemand: `sw.js` lag im Build, und die vorab geladenen Kacheln der Route
 * (`$lib/tracking/tileCache.ts`) lagen im Cache `osm-tiles`, ohne dass sie je
 * jemand auslieferte. Offline blieb die Karte leer.
 *
 * Bewusst **nicht** über `virtual:pwa-register`: Dessen Workbox-Hülle hängt im
 * Modus `prompt` an `controlling` ein `location.reload()`. Hier soll nie etwas
 * neu laden. Ein neuer Service Worker wartet, bis jede Seite der Instanz
 * geschlossen ist (kein `skipWaiting`, siehe `vite.config.ts`). Die Tracking-Ansicht
 * im Einsatz läuft also mit dem Stand weiter, mit dem sie geöffnet wurde.
 */
export async function serviceWorkerAnmelden(): Promise<void> {
	if (import.meta.env.DEV || !('serviceWorker' in navigator)) return;
	try {
		// `updateViaCache: 'none'`: Ob es einen neuen Stand gibt, fragt der Browser
		// ohne HTTP-Cache. Nightly deployt mehrmals täglich.
		await navigator.serviceWorker.register('/sw.js', { scope: '/', updateViaCache: 'none' });
	} catch (e) {
		// Ohne Service Worker läuft die App weiter, nur ohne Offline-Kacheln.
		console.warn('Service Worker nicht registriert:', e);
	}
}
