import { test, expect, type Page } from '@playwright/test';
import { blockExternal, konvoiFahrzeug, mockOrgPortal } from './fixtures';

// Der Hinweis, dass der Lizenzschlüssel bald abläuft
// (src/lib/components/LizenzAblaufHinweis.svelte). Zusagen, die man einem
// Bildschirmfoto nicht ansieht:
//  - er erscheint nur, wenn das Backend warnen will (`expiry_warning`) —
//    ein Schlüssel mit 30 Jahren Laufzeit zeigt nach einem Update nichts;
//  - er fragt mit der Superadmin-Sitzung, nicht mit der Organisationssitzung
//    der Seite — sonst bekäme er unter /o/<slug>/ ein 403 und schwiege;
//  - wer kein Superadmin ist, sieht ihn nicht und löst auch keine Anfrage aus.

const SLUG = 'lizenz-org';
const CONVOY = 'c-lizenz';

function status(tage: number, warnen: boolean) {
	return {
		valid: true, demo_mode: false, license_id: '', customer: 'FF Musterstadt', email: null,
		issued: null, expires: '2026-10-20', expires_in_days: tage, expiry_warning: warnen,
		max_users: null, instance_id: 'inst-1', key_source: 'db', error: null,
		contract: 'wartung_basis', contract_until: null, contract_ended: false,
		max_orgs: 1, orgs_limit: 1, orgs_count: 1,
	};
}

async function oeffnen(page: Page, antwort: object, opts: { superadmin?: boolean } = {}) {
	await blockExternal(page);
	await page.routeWebSocket(/\/api\/ws\//, () => {});
	await mockOrgPortal(page, {
		slug: SLUG, convoyId: CONVOY, rolle: 'planer',
		fahrzeuge: [konvoiFahrzeug({ position: 1, vehicle: { id: 'v1', name: 'LF 10' } })],
	});
	await page.route('**/api/org/plan', (route) => route.fulfill({ json: { plan: null } }));
	if (opts.superadmin === false) {
		// Die globale Sitzung ohne Superadmin — später registriert, gewinnt also.
		await page.route('**/api/auth/me', (route) => {
			if (route.request().headers()['x-org-slug']) return route.fallback();
			route.fulfill({ status: 401, json: { detail: 'Not authenticated' } });
		});
	}
	const anfragen: { orgKopf: string | undefined }[] = [];
	await page.route('**/api/license/status', (route) => {
		anfragen.push({ orgKopf: route.request().headers()['x-org-slug'] });
		route.fulfill({ json: antwort });
	});
	await page.goto(`/o/${SLUG}/tracking/${CONVOY}`, { waitUntil: 'domcontentloaded' });
	await expect(page.getByRole('combobox', { name: 'Meine Position' })).toBeVisible();
	return anfragen;
}

const hinweis = (page: Page) => page.locator('.lizenz-ablauf');

test('der Superadmin sieht den nahen Ablauf – gefragt mit seiner eigenen Sitzung', async ({ page }) => {
	const anfragen = await oeffnen(page, status(20, true));
	await expect(hinweis(page)).toContainText('läuft in 20 Tagen ab');
	await expect(hinweis(page)).toContainText('20.10.2026');
	await expect(hinweis(page)).toContainText('Demo-Modus');
	await expect(hinweis(page).getByRole('link')).toHaveAttribute('href', '/admin');
	expect(anfragen.length).toBeGreaterThan(0);
	expect(anfragen.every((a) => a.orgKopf === undefined)).toBe(true);
});

test('eine Woche vorher wird der Hinweis dringend', async ({ page }) => {
	await oeffnen(page, status(1, true));
	await expect(hinweis(page)).toContainText('läuft morgen ab');
	await expect(hinweis(page)).toHaveAttribute('role', 'alert');
});

test('ohne Warnung vom Backend steht dort nichts', async ({ page }) => {
	const anfragen = await oeffnen(page, status(10_950, false));
	await expect.poll(() => anfragen.length).toBeGreaterThan(0);
	await expect(hinweis(page)).toHaveCount(0);
});

test('wer kein Superadmin ist, sieht nichts und fragt nicht', async ({ page }) => {
	const anfragen = await oeffnen(page, status(3, true), { superadmin: false });
	await expect(hinweis(page)).toHaveCount(0);
	expect(anfragen).toHaveLength(0);
});
