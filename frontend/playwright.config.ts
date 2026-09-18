import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-End-Tests der QR-Weitergabe.
 *
 * Zwei Server, weil die zwei Testgegenstände unterschiedlich erreichbar sind:
 * Die **Tracking-Ansicht** ist öffentlich, läuft also in der echten App — nur
 * die API-Antwort wird abgefangen. Der **Teilen-Dialog** sitzt hinter der
 * Anmeldung; ihn über die halbe Planungsseite nachzubauen hieße, ein Dutzend
 * Endpunkte zu erfinden, deshalb mountet ihn eine schlanke Hülle unter
 * `e2e/harness/` mit gestubbter `$lib/api`. Der Produktionsbau kennt sie nicht.
 */
export default defineConfig({
	testDir: './e2e',
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 1 : 0,
	workers: process.env.CI ? 1 : undefined,
	reporter: process.env.CI ? [['github'], ['list']] : [['list']],
	use: {
		baseURL: 'http://localhost:4173',
		trace: 'on-first-retry',
		// Kein Netz nach draußen: Die Tests fangen alles ab, was sie brauchen.
		// Was trotzdem hinausginge (Kartenkacheln), soll auffallen statt hängen.
		navigationTimeout: 15_000,
	},
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
	webServer: [
		{
			// Gebauter Stand statt `vite dev`: Der Entwicklungsserver übersetzt beim
			// ersten Zugriff und lässt parallele Tests in den Zeitablauf laufen.
			command: 'npm run build && npm run preview -- --port 4173 --strictPort',
			url: 'http://localhost:4173/',
			reuseExistingServer: !process.env.CI,
			timeout: 180_000,
		},
		{
			command: 'npx vite --config e2e/harness/vite.config.ts',
			url: 'http://localhost:4174/',
			reuseExistingServer: !process.env.CI,
			timeout: 120_000,
		},
	],
});
