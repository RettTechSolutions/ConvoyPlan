import { test, expect, type Page } from '@playwright/test';
import { blockExternal } from './fixtures';

/**
 * Der MCP-Zustimmungsschirm `/oauth/consent` für ein gewöhnliches Mitglied.
 *
 * Wer sich in ConvoyPlan anmeldet, tut das in einer Organisation; eine
 * *globale* Sitzung hat nur der Superadmin. Das Wurzel-Layout schickt aber
 * jede Seite außerhalb von `PUBLIC_ROUTES` ohne globale Sitzung auf `/admin` —
 * die Superadmin-Anmeldung. Der Zustimmungsschirm stand nicht in der Liste:
 * ein Mitglied mit gültiger Org-Sitzung landete beim Verbinden von ChatGPT &
 * Co. dort, wo es sich gar nicht anmelden kann.
 *
 * Die Seite prüft die Anmeldung selbst (`GET /api/mcp/consent` über
 * `get_current_person`, 401 → Anmeldung mit Rücksprung). Hier steht, dass ihr
 * das Layout nicht dazwischenfunkt.
 */

const TICKET = 'mcp.ticket.abc';

async function oeffnen(page: Page, consent: { status: number; json: unknown }) {
	await blockExternal(page);
	await page.route('**/api/**', (r) => r.fulfill({ status: 404, json: { detail: 'Not Found' } }));
	// Keine globale Sitzung — der Normalfall für ein Mitglied.
	await page.route('**/api/auth/me', (r) => r.fulfill({ status: 401, json: { detail: 'Not authenticated' } }));
	await page.route('**/api/mcp/consent**', (r) => r.fulfill(consent));
	await page.goto(`/oauth/consent?request=${encodeURIComponent(TICKET)}`);
}

test('ein Mitglied mit Org-Sitzung sieht den Zustimmungsschirm — nicht die Superadmin-Anmeldung', async ({ page }) => {
	await oeffnen(page, {
		status: 200,
		json: {
			client_id: 'c1',
			client_name: 'ChatGPT',
			client_name_verified: false,
			redirect_host: 'chatgpt.com',
			requested_scopes: [{ scope: 'convoy:read', label: 'Konvois lesen' }],
			optional_scopes: [],
			organizations: [
				{
					id: 'o1', name: 'THW OV Musterstadt', slug: 'thw-musterstadt', role: 'planer',
					mcp_enabled: true, bereiche: [], grantable_scopes: ['convoy:read'], optional_scopes: [],
				},
			],
			expires_at: '2026-10-09T15:00:00Z',
		},
	});

	await expect(page.getByRole('heading', { name: 'Zugriff erlauben?' })).toBeVisible();
	// Das Layout entscheidet erst, wenn `/api/auth/me` geantwortet hat — also
	// kurz warten und dann noch einmal hinsehen.
	await page.waitForTimeout(1_000);
	expect(new URL(page.url()).pathname).toBe('/oauth/consent');
	await expect(page.getByRole('heading', { name: 'Zugriff erlauben?' })).toBeVisible();
});

test('ohne Anmeldung geht es zur Anmeldung mit Rücksprung — nicht auf /admin', async ({ page }) => {
	await oeffnen(page, { status: 401, json: { detail: 'Not authenticated' } });
	await page.waitForURL((url) => url.pathname === '/' && url.searchParams.has('redirect'));
	expect(new URL(page.url()).searchParams.get('redirect')).toBe(
		`/oauth/consent?request=${encodeURIComponent(TICKET)}`,
	);
	await page.waitForTimeout(1_000);
	expect(new URL(page.url()).pathname).toBe('/');
});
