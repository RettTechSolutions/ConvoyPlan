/**
 * Meldet den Service Worker an (`sw.js`, erzeugt von `@vite-pwa/sveltekit`).
 *
 * Unter SvelteKit registriert er sich **nicht** von selbst: Das Plugin baut ihn
 * und `registerSW.js`, aber keine Seite lud beides — bis 2026-11 lief deshalb
 * auf keinem Gerät ein Service Worker, und der Kachelkorridor, den
 * `$lib/tracking/tileCache.ts` vorab in `osm-tiles` legt, wurde im Funkloch nie
 * ausgeliefert. Aufgerufen aus dem Wurzel-Layout, also auf jeder Route; der
 * Scope ist `/` und schließt `/track` ein.
 *
 * Wie er sich verhält, steht in `vite.config.ts` (`generateSW`): ein neuer
 * Service Worker wartet, bis alle Tabs zu sind — ein Fahrer-Link wird nie
 * mitten im Einsatz neu geladen. Geprüft von `e2e/service-worker.spec.ts`.
 */
export async function serviceWorkerAnmelden(): Promise<void> {
	if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return;
	try {
		const { registerSW } = await import('virtual:pwa-register');
		registerSW({
			immediate: true,
			onRegisterError(fehler: unknown) {
				// Ohne Service Worker läuft die App weiter, nur ohne Offline-Kacheln.
				console.warn('Service Worker nicht angemeldet:', fehler);
			},
		});
	} catch (fehler) {
		console.warn('Service Worker nicht angemeldet:', fehler);
	}
}
