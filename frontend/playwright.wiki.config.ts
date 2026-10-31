import { defineConfig, devices } from '@playwright/test';

/**
 * Bilder fürs Wiki — kein Test, sondern ein Lauf, der sie erzeugt:
 * `npm run wiki:bilder`, Ergebnis in `../wiki/bilder/`.
 *
 * Dieselbe Lage wie die E2E-Tests (`e2e/kontextmenue-attrappe.ts`), damit ein
 * Bild nie etwas zeigt, das die Tests nicht auch prüfen. Anders als dort lädt
 * die Karte echte OSM-Kacheln — eine graue Fläche erklärt nichts. Deshalb
 * braucht dieser Lauf Netz und läuft nicht in der CI.
 */
export default defineConfig({
	testDir: './wiki-bilder',
	testMatch: '*.bilder.ts',
	workers: 1,
	reporter: [['list']],
	use: {
		...devices['Desktop Chrome'],
		baseURL: 'http://localhost:4173',
		viewport: { width: 1280, height: 760 },
		deviceScaleFactor: 2,
		colorScheme: 'dark',
	},
	webServer: [
		{
			command: 'npm run build && npm run preview -- --port 4173 --strictPort',
			url: 'http://localhost:4173/',
			reuseExistingServer: true,
			timeout: 180_000,
		},
		{
			// Die Komponentenhülle für den Teilen-Dialog, wie in den E2E-Tests.
			command: 'npx vite --config e2e/harness/vite.config.ts',
			url: 'http://localhost:4174/',
			reuseExistingServer: true,
			timeout: 120_000,
		},
	],
});
