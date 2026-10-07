import { test, expect, type Page } from '@playwright/test';
import { blockExternal } from './fixtures';

/**
 * Die Seite `/oauth/app`: Anmeldung der Begleit-App über den Browser.
 *
 * Entschieden wird am Server (`backend/tests/test_app_anmeldung.py`); hier
 * steht, was die Seite mit seinen Antworten macht — und was sie **nicht**
 * macht: ohne Klick einen Code holen, wenn der Server eine Bestätigung will.
 *
 * - 401 → zur Anmeldung **dieser** Organisation, mit Rücksprung hierher;
 * - 409 → die Frage mit Konto und Organisation; erst der Klick schickt
 *   `bestaetigt`, „Abbrechen" schickt `abbrechen`;
 * - 200 → zurück zur App (eigenes Schema), mit einem Link als Rückfalloption.
 */

const SLUG = 'thw-musterstadt';
const TICKET = 'ticket.abc.def';
const ZURUECK = 'de.convoyplan.companion:/oauth?code=c0de&state=s&iss=https%3A%2F%2Finstanz';

type Antwort = { status: number; json: unknown };

async function seite(page: Page, antworten: Antwort[]) {
	const posts: Record<string, unknown>[] = [];
	await blockExternal(page);
	await page.route('**/api/**', (r) => r.fulfill({ status: 404, json: { detail: 'Not Found' } }));
	// Für den Weg zur Anmeldeseite: sie kennt die Organisation, niemand ist angemeldet.
	await page.route('**/api/auth/me', (r) => r.fulfill({ status: 401, json: { detail: 'Not authenticated' } }));
	await page.route('**/api/auth/org-lookup**', (r) =>
		r.fulfill({ json: { name: 'THW OV Musterstadt', slug: SLUG } }),
	);
	await page.route('**/api/oauth/app/anfrage**', (r) => {
		if (r.request().method() === 'GET') {
			r.fulfill({ json: { org_slug: SLUG, org_name: 'THW OV Musterstadt', expires_at: '2026-10-07T15:00:00Z' } });
			return;
		}
		posts.push(JSON.parse(r.request().postData() ?? '{}'));
		const a = antworten[Math.min(posts.length - 1, antworten.length - 1)];
		r.fulfill({ status: a.status, json: a.json });
	});
	// Die Navigation auf das eigene Schema der App kann Chromium nicht
	// ausführen; die Seite bleibt stehen und zeigt den Rückfall-Link.
	await page.goto(`/oauth/app?request=${encodeURIComponent(TICKET)}`);
	return posts;
}

test('ohne Anmeldung geht es zur Anmeldung dieser Organisation und zurück', async ({ page }) => {
	await seite(page, [{ status: 401, json: { detail: 'Nicht angemeldet' } }]);
	await page.waitForURL(`**/o/${SLUG}/login?redirect=*`);
	const ziel = new URL(page.url()).searchParams.get('redirect');
	expect(ziel).toBe(`/oauth/app?request=${encodeURIComponent(TICKET)}`);
});

test('eine bestehende Sitzung braucht einen Klick — erst der schickt „bestaetigt"', async ({ page }) => {
	const posts = await seite(page, [
		{ status: 409, json: { detail: { bestaetigen: true, email: 'planer@example.org', org_name: 'THW OV Musterstadt' } } },
		{ status: 200, json: { redirect_url: ZURUECK } },
	]);

	const frage = page.getByTestId('bestaetigen');
	await expect(frage).toContainText('planer@example.org');
	await expect(frage).toContainText('THW OV Musterstadt');
	// Bis hierher genau eine Anfrage, und die ohne Bestätigung.
	expect(posts).toEqual([{ request: TICKET }]);

	await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
	await expect(page.getByRole('link', { name: 'App öffnen' })).toHaveAttribute('href', ZURUECK);
	expect(posts[1]).toEqual({ request: TICKET, bestaetigt: true });
});

test('„Abbrechen" schickt abbrechen und keine Bestätigung', async ({ page }) => {
	const posts = await seite(page, [
		{ status: 409, json: { detail: { bestaetigen: true, email: 'planer@example.org', org_name: 'THW OV Musterstadt' } } },
		{ status: 200, json: { redirect_url: 'de.convoyplan.companion:/oauth?error=access_denied&state=s' } },
	]);
	await page.getByRole('button', { name: 'Abbrechen', exact: true }).click();
	await expect.poll(() => posts.length).toBe(2);
	expect(posts[1]).toEqual({ request: TICKET, abbrechen: true });
});

test('frisch angemeldet: ohne Frage zurück zur App', async ({ page }) => {
	const posts = await seite(page, [{ status: 200, json: { redirect_url: ZURUECK } }]);
	await expect(page.getByRole('link', { name: 'App öffnen' })).toHaveAttribute('href', ZURUECK);
	await expect(page.getByTestId('bestaetigen')).toHaveCount(0);
	expect(posts).toEqual([{ request: TICKET }]);
});
