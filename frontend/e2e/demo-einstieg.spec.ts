import { test, expect, type Page } from '@playwright/test';
import { blockExternal } from './fixtures';

/**
 * Die Zusage: **der Demo-Einstieg ist ohne Anmeldung erreichbar.**
 *
 * Genau daran scheiterte er. Der Wächter im Wurzel-Layout schickt jeden
 * nicht angemeldeten Aufruf eines nicht-öffentlichen Pfades auf `/admin`, und
 * `/demo` stand nicht auf der Liste der öffentlichen Pfade. Wer die Demo
 * wollte, landete auf der Anmeldemaske — der einen Seite, an der er sich
 * mangels Zugang gerade nicht anmelden kann.
 *
 * Auffallen konnte das nirgends: die Demo-Seite selbst ist fehlerfrei, sie
 * wird nur nie erreicht. Sichtbar wird der Fehler erst im Zusammenspiel mit
 * dem Layout darüber — also genau so, wie dieser Test die Seite öffnet: als
 * echter Seitenaufbau einer Sitzung, die es nicht gibt.
 */

type Instanz = {
	/** Die Pfade, die das Hauptfenster angesteuert hat — `goto()` des Wächters
	 *  navigiert im selben Dokument und ist im Ergebnis nicht von einem
	 *  regulären Seitenwechsel zu unterscheiden. */
	pfade: string[];
	/** Ob der Wächter die Sitzung schon erfragt hat. Erst danach entscheidet er. */
	sitzungGeprueft: () => boolean;
};

/** Eine Instanz ohne jede Sitzung: `/api/auth/me` antwortet mit 401. */
async function ohneAnmeldung(page: Page, opts: { demoAn?: boolean } = {}): Promise<Instanz> {
	await blockExternal(page);
	await page.route('**/api/branding**', (route) => route.fulfill({ json: {} }));
	await page.route('**/api/setup/status', (route) => route.fulfill({ json: { setup_required: false } }));
	await page.route('**/api/auth/demo-status', (route) =>
		route.fulfill({ json: { enabled: opts.demoAn ?? true, session_hours: 24 } }),
	);
	await page.route('**/api/auth/demo-followup/unsubscribe', (route) =>
		route.fulfill({ json: { status: 'ok' } }),
	);

	let geprueft = false;
	await page.route('**/api/auth/me**', (route) => {
		geprueft = true;
		route.fulfill({ status: 401, json: { detail: 'Not authenticated' } });
	});

	const pfade: string[] = [];
	page.on('framenavigated', (frame) => {
		if (frame === page.mainFrame()) pfade.push(new URL(frame.url()).pathname);
	});

	return { pfade, sitzungGeprueft: () => geprueft };
}

/**
 * Wartet, bis der Wächter entschieden haben *kann*: Sitzungsprüfung beantwortet
 * plus Nachlauf. Ohne den Nachlauf liefe der Test dem Redirect davon und wäre
 * grün, obwohl er gleich käme.
 */
async function wächterHatEntschieden(instanz: Instanz) {
	await expect.poll(instanz.sitzungGeprueft).toBe(true);
	await new Promise((fertig) => setTimeout(fertig, 500));
}

test.describe('Demo-Einstieg ohne Anmeldung', () => {
	test('/demo zeigt das Formular statt der Anmeldemaske', async ({ page }) => {
		const instanz = await ohneAnmeldung(page);

		await page.goto('/demo', { waitUntil: 'domcontentloaded' });

		await expect(page.locator('.status')).toHaveText('Demo starten');
		await expect(page.locator('#demo-email')).toBeVisible();

		await wächterHatEntschieden(instanz);
		expect(instanz.pfade).not.toContain('/admin');
		expect(new URL(page.url()).pathname).toBe('/demo');
	});

	test('auch die abgeschaltete Demo sagt das, statt umzuleiten', async ({ page }) => {
		// Die Absage gehört der Demo-Seite. Wer hier auf /admin landete, wüsste
		// nicht einmal, woran er ist.
		const instanz = await ohneAnmeldung(page, { demoAn: false });

		await page.goto('/demo', { waitUntil: 'domcontentloaded' });

		await expect(page.locator('.error')).toContainText('nicht verfügbar');

		await wächterHatEntschieden(instanz);
		expect(instanz.pfade).not.toContain('/admin');
	});

	test('der Abmeldelink aus der E-Mail führt nicht auf die Anmeldung', async ({ page }) => {
		// Wer abbestellt, hat keine Sitzung — das ist der Normalfall dieses
		// Links und nicht die Ausnahme.
		const instanz = await ohneAnmeldung(page);

		await page.goto('/demo/abmelden?token=abc123', { waitUntil: 'domcontentloaded' });

		await expect(page.locator('.status')).toHaveText('Abgemeldet');

		await wächterHatEntschieden(instanz);
		expect(instanz.pfade).not.toContain('/admin');
	});
});
