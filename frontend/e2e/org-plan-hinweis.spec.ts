import { test, expect, type Page } from '@playwright/test';
import { blockExternal, konvoiFahrzeug, mockOrgPortal } from './fixtures';

// Der Hinweis auf den Plan einer Organisation (Hosting, Einsatz-Paket).
// Drei Zusagen, die man einem Bildschirmfoto nicht ansieht:
//  - ohne Plan steht dort nichts — der Normalfall jeder eigenen Installation
//    darf nach einem Update keine Warnung zeigen;
//  - dass eine Organisation nur noch lesbar ist, sieht jeder, auch ein
//    Beobachter — sonst sucht jemand den Fehler beim Speichern;
//  - eine Überschreitung der gebuchten Grenzen sehen die, die planen, und
//    sie sagt ausdrücklich, dass nichts eingeschränkt ist.

const SLUG = 'plan-org';
const CONVOY = 'c-plan';

const OHNE_PLAN = {
	plan: null, label: null, max_vehicles: null, max_planners: null, max_trackers: null, valid_until: null,
	vehicles: 3, planners: 2, trackers: 0, vehicles_over: false, planners_over: false, trackers_over: false,
	expired: false, locked: false, days_left: null, locked_from: null,
};

async function oeffnen(page: Page, plan: object, rolle: 'beobachter' | 'planer' | 'admin') {
	await blockExternal(page);
	await page.routeWebSocket(/\/api\/ws\//, () => {});
	await mockOrgPortal(page, {
		slug: SLUG, convoyId: CONVOY, rolle,
		fahrzeuge: [konvoiFahrzeug({ position: 1, vehicle: { id: 'v1', name: 'LF 10' } })],
	});
	await page.route('**/api/org/plan', (route) => route.fulfill({ json: plan }));
	const geladen = page.waitForResponse('**/api/org/plan');
	await page.goto(`/o/${SLUG}/tracking/${CONVOY}`, { waitUntil: 'domcontentloaded' });
	await geladen;
}

const hinweis = (page: Page) => page.locator('.plan-hinweis');

test('ohne Plan erscheint kein Hinweis', async ({ page }) => {
	await oeffnen(page, OHNE_PLAN, 'admin');
	await expect(page.getByRole('combobox', { name: 'Meine Position' })).toBeVisible();
	await expect(hinweis(page)).toHaveCount(0);
});

test('die Sperre nach Ablauf sieht auch ein Beobachter', async ({ page }) => {
	await oeffnen(page, {
		...OHNE_PLAN, plan: 'einsatz', label: 'Einsatz-Paket', max_vehicles: 50, max_planners: 10,
		valid_until: '2026-08-01', expired: true, locked: true, days_left: -60, locked_from: '2026-08-16',
	}, 'beobachter');
	await expect(hinweis(page)).toContainText('nur noch lesbar');
	await expect(hinweis(page)).toContainText('01.08.2026');
	await expect(hinweis(page)).toHaveAttribute('role', 'alert');
});

test('eine Überschreitung sehen die, die planen — und nichts ist gesperrt', async ({ page }) => {
	const ueber = {
		...OHNE_PLAN, plan: 'hosting_s', label: 'Hosting S', max_vehicles: 25, max_planners: 5,
		vehicles: 27, vehicles_over: true,
	};
	await oeffnen(page, ueber, 'planer');
	await expect(hinweis(page)).toContainText('27 Fahrzeuge (enthalten: 25)');
	await expect(hinweis(page)).toContainText('nichts eingeschränkt');
});

test('mehr Tracker als gebucht stehen im selben Hinweis', async ({ page }) => {
	await oeffnen(page, {
		...OHNE_PLAN, plan: 'hosting_s', label: 'Hosting S', max_vehicles: 25, max_planners: 5, max_trackers: 2,
		trackers: 3, trackers_over: true,
	}, 'admin');
	await expect(hinweis(page)).toContainText('3 Tracker (enthalten: 2)');
	await expect(hinweis(page)).toContainText('nichts eingeschränkt');
});

test('ein Beobachter bekommt die Überschreitung nicht angezeigt', async ({ page }) => {
	await oeffnen(page, {
		...OHNE_PLAN, plan: 'hosting_s', label: 'Hosting S', max_vehicles: 25, max_planners: 5,
		vehicles: 27, vehicles_over: true,
	}, 'beobachter');
	await expect(page.getByRole('combobox', { name: 'Meine Position' })).toBeVisible();
	await expect(hinweis(page)).toHaveCount(0);
});
