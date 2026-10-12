import { test, expect, type Page, type Request } from '@playwright/test';
import { blockExternal } from './fixtures';

// Kontextmenü in Planung, Org-Admin und Admin-Bereich — in der echten App,
// mit abgefangener API. Die Zusage, die man einem Bildschirmfoto nicht
// ansieht: **jeder Eintrag schickt denselben Aufruf wie der Knopf daneben.**
// Deshalb prüfen die Tests nicht nur, dass ein Eintrag dasteht, sondern was
// beim Server ankommt — Pfad, Methode und Körper.
//
// Die Mechanik selbst (Tastatur, Browsermenü in Feldern, Rand, langes Drücken)
// steht in `kontextmenue.spec.ts`.

const SLUG = 'km-plan';
const ORG = 'o1';
const CONVOY = 'c1';

/** Ein schreibender Aufruf, wie er beim Server ankam. */
type Aufruf = { methode: string; pfad: string; koerper: unknown };

type Antwort = unknown | ((req: Request) => unknown);

/**
 * Fängt `/api/**` ab: bekannte Pfade bekommen ihre Antwort, unbekannte
 * GET-Aufrufe ein 404 (die Seiten fangen das ab), jeder schreibende Aufruf
 * landet in der Liste und bekommt `{}`.
 */
async function mockApi(page: Page, antworten: Record<string, Antwort>): Promise<Aufruf[]> {
	const aufrufe: Aufruf[] = [];
	await blockExternal(page);
	await page.routeWebSocket(/\/api\/ws\//, () => {});
	await page.route('**/api/**', (route) => {
		const req = route.request();
		const pfad = new URL(req.url()).pathname;
		const methode = req.method();
		const schluessel = `${methode} ${pfad}`;
		// Das Ticket für den Live-Kanal holt die Seite selbst; es ist kein Klick.
		if (methode !== 'GET' && pfad !== '/api/auth/stream-ticket') {
			let koerper: unknown = null;
			try { koerper = req.postDataJSON(); } catch { koerper = req.postData(); }
			aufrufe.push({ methode, pfad, koerper });
		}
		if (schluessel in antworten) {
			const a = antworten[schluessel];
			return route.fulfill({ json: typeof a === 'function' ? (a as (r: Request) => unknown)(req) : a });
		}
		if (methode === 'GET') return route.fulfill({ status: 404, json: { detail: 'nicht im Test' } });
		return route.fulfill({ json: {} });
	});
	return aufrufe;
}

/** `/api/auth/me`: mit `X-Org-Slug` ein Org-Admin, ohne die Superadmin-Sitzung. */
function ich(req: Request) {
	if (req.headers()['x-org-slug'] === SLUG) {
		return {
			user_id: 'u-admin', email: 'admin@example.org', is_superadmin: false,
			org_id: ORG, org_slug: SLUG, org_name: 'THW OV Musterstadt', role: 'admin', is_demo: false,
		};
	}
	return {
		user_id: 'u-super', email: 'super@example.org', is_superadmin: true,
		org_id: null, org_slug: null, org_name: null, role: null, is_demo: false,
	};
}

const GRUNDLAGE: Record<string, Antwort> = {
	'GET /api/setup/status': { setup_required: false },
	'GET /api/license/mode': { demo_mode: false },
	'GET /api/auth/me': ich,
};

const menue = (page: Page) => page.getByRole('menu');
const eintrag = (page: Page, name: string) => menue(page).getByRole('menuitem', { name, exact: true });

// ── Planung ────────────────────────────────────────────────────────────

function fahrzeug(id: string, name: string, callsign: string | null, order_index: number) {
	return {
		id, name, callsign, license_plate: null, height_cm: null, weight_kg: null, length_cm: null,
		convoy_role: null, axle_load_kg: null, propulsion: 'combustion',
		tank_capacity_l: null, fuel_consumption_l100km: null, current_fuel_l: null,
		battery_capacity_kwh: null, consumption_kwh_100km: null, current_charge_kwh: null,
		staerke_soll_fuehrer: null, staerke_soll_unterfuehrer: null, staerke_soll_mannschaften: null,
		order_index, range_km: null, range_uses_defaults: false,
	};
}

const HLF = fahrzeug('v-hlf', 'HLF 20', 'Florian 1/46', 0);
const MTW = fahrzeug('v-mtw', 'MTW', 'Florian 1/19', 1);
const ELW = fahrzeug('v-elw', 'ELW 1', null, 2);

function wegpunkt(id: string, name: string, lat: number, lon: number, order_index: number) {
	return {
		id, name, type: 'waypoint', lat, lon, planned_arrival: null, planned_departure: null,
		hold_duration_min: 0, halt_purpose: null, notes: null, order_index,
	};
}

function imVerband(v: ReturnType<typeof fahrzeug>, position: number) {
	return {
		vehicle: v, position, vehicle_status: 'planned', status_level: null, status_note: null,
		status_changed_at: null, sonderfunktion: null, mobile_phone: null,
		staerke_soll_fuehrer: null, staerke_soll_unterfuehrer: null, staerke_soll_mannschaften: null,
		staerke_ist_fuehrer: null, staerke_ist_unterfuehrer: null, staerke_ist_mannschaften: null,
	};
}

const KONVOI = {
	id: CONVOY, name: 'Verlegung Nord', organization: 'THW OV Musterstadt', organization_id: ORG,
	parent_convoy_id: null, start_time: null, speed_urban_kmh: 40, speed_rural_kmh: 70,
	road_preference: 'standard', spacing_urban_m: 20, spacing_rural_m: 50, spacing_motorway_m: 100,
	status: 'planning', share_token: 'tok-123', created_at: '2026-10-01T08:00:00Z',
	start_point: { lat: 49.79, lon: 9.93 }, end_point: { lat: 51.34, lon: 12.37 },
	convoy_vehicles: [imVerband(HLF, 0), imVerband(MTW, 1), imVerband(ELW, 2)],
	waypoints: [
		wegpunkt('wp-fulda', 'WP Fulda', 50.55, 9.68, 0),
		wegpunkt('wp-erfurt', 'WP Erfurt', 50.98, 11.03, 1),
		wegpunkt('wp-jena', 'WP Jena', 50.93, 11.59, 2),
	],
	lage: null, auftrag: null, marschform: null, ablaufpunkt: null, ablaufzeit: null,
	ablaufführer: null, versorgung: null, funkgruppe: null, anlagen: null,
};

async function planung(page: Page): Promise<Aufruf[]> {
	const aufrufe = await mockApi(page, {
		...GRUNDLAGE,
		'GET /api/vehicles/': [HLF, MTW, ELW],
		'GET /api/convoys/': [KONVOI],
		[`GET /api/convoys/${CONVOY}`]: KONVOI,
		[`GET /api/convoys/${CONVOY}/route`]: null,
		'GET /api/organizations/': [],
	});
	// Das Tutorial für Erstbesucher legt sich sonst über alles.
	await page.addInitScript((slug) => localStorage.setItem(`cp_tutorial_seen_v1__${slug}`, '1'), SLUG);
	await page.goto(`/o/${SLUG}/plan`, { waitUntil: 'domcontentloaded' });
	await expect(page.locator('.maplibregl-marker', { hasText: 'WP Erfurt' })).toBeAttached();
	return aufrufe;
}

const tab = (page: Page, name: string) => page.locator('.tab', { hasText: name }).first();

test('Planung · Karte: „Start hier setzen" schickt den Punkt unter dem Zeiger', async ({ page }) => {
	const aufrufe = await planung(page);
	const karte = page.locator('.map-area .maplibregl-canvas');
	const box = (await karte.boundingBox())!;
	// Links unten auf der Karte: weg von Markern, Zoomknöpfen und Hinweisleisten.
	await karte.click({ button: 'right', position: { x: box.width * 0.25, y: box.height * 0.8 } });

	await expect(menue(page)).toBeVisible();
	// Titel: die Koordinaten des Punkts.
	await expect(menue(page).locator('.titel').first()).toHaveText(/^\d+\.\d{5}, \d+\.\d{5}$/);
	await expect(eintrag(page, 'Route berechnen')).toBeEnabled();
	await expect(menue(page).getByRole('menuitemcheckbox', { name: 'Sperrungen anzeigen' })).toHaveAttribute('aria-checked', 'false');
	await expect(eintrag(page, 'Koordinaten kopieren')).toBeVisible();

	await eintrag(page, 'Start hier setzen').click();
	await expect.poll(() => aufrufe.find((a) => a.methode === 'PUT')).toBeTruthy();
	const put = aufrufe.find((a) => a.methode === 'PUT')!;
	expect(put.pfad).toBe(`/api/convoys/${CONVOY}`);
	const start = (put.koerper as { start_point: { lat: number; lon: number } }).start_point;
	// Irgendwo im sichtbaren Ausschnitt um Deutschland — nicht 0/0, nicht der alte Start.
	expect(start.lat).toBeGreaterThan(40);
	expect(start.lat).toBeLessThan(60);
	expect(start).not.toEqual(KONVOI.start_point);
	expect(Object.keys(put.koerper as object)).toEqual(['start_point']);
});

test('Planung · Karte: Rechtsklick auf einen Wegpunkt-Marker zeigt dessen Menü', async ({ page }) => {
	await planung(page);
	await page.locator('.maplibregl-marker', { hasText: 'WP Erfurt' }).click({ button: 'right', position: { x: 6, y: 6 } });
	await expect(menue(page).locator('.titel').first()).toHaveText('WP Erfurt');
	await expect(eintrag(page, 'Bearbeiten')).toBeVisible();
	await expect(eintrag(page, 'Löschen')).toBeVisible();
	// Kein Kartenmenü darunter oder daneben.
	await expect(eintrag(page, 'Start hier setzen')).toHaveCount(0);
	await expect(menue(page)).toHaveCount(1);
});

test('Planung · Wegpunkte: Umsortieren und Löschen gehen denselben Weg wie Ziehen und ✕', async ({ page }) => {
	const aufrufe = await planung(page);
	await tab(page, 'Wegpunkte').click();
	const zeile = (name: string) => page.locator('.wp-item', { hasText: name });

	// Der erste Punkt kann nicht weiter nach oben.
	await zeile('WP Fulda').click({ button: 'right', position: { x: 8, y: 8 } });
	await expect(eintrag(page, 'Nach oben')).toBeDisabled();
	await page.keyboard.press('Escape');

	await zeile('WP Jena').click({ button: 'right', position: { x: 8, y: 8 } });
	await eintrag(page, 'An den Anfang').click();
	await expect.poll(() => aufrufe.filter((a) => a.methode === 'PATCH').length).toBe(1);
	expect(aufrufe[0]).toEqual({
		methode: 'PATCH',
		pfad: `/api/convoys/${CONVOY}/waypoints/reorder`,
		koerper: [
			{ id: 'wp-jena', order_index: 0 },
			{ id: 'wp-fulda', order_index: 1 },
			{ id: 'wp-erfurt', order_index: 2 },
		],
	});
	await expect(page.locator('.wp-item').first()).toContainText('WP Jena');

	await zeile('WP Erfurt').click({ button: 'right', position: { x: 8, y: 8 } });
	await eintrag(page, 'Löschen').click();
	await expect.poll(() => aufrufe.some((a) => a.methode === 'DELETE')).toBe(true);
	expect(aufrufe.find((a) => a.methode === 'DELETE')!.pfad).toBe(`/api/convoys/${CONVOY}/waypoints/wp-erfurt`);
});

test('Planung · Marschfolge: „An die Spitze" speichert die neue Reihenfolge', async ({ page }) => {
	const aufrufe = await planung(page);
	await tab(page, 'Fahrzeuge').click();
	const reihe = page.locator('.convoy-vehicle-row', { hasText: 'ELW 1' });
	await reihe.click({ button: 'right', position: { x: 8, y: 8 } });
	await expect(menue(page).locator('.titel').first()).toHaveText('3. ELW 1');
	// Ohne Funkrufnamen gibt es nichts zu kopieren.
	await expect(eintrag(page, 'Funkrufname kopieren')).toHaveCount(0);
	await eintrag(page, 'An die Spitze').click();

	await expect.poll(() => aufrufe.find((a) => a.pfad.endsWith('/vehicles/reorder'))).toBeTruthy();
	expect(aufrufe.find((a) => a.pfad.endsWith('/vehicles/reorder'))!.koerper).toEqual([
		{ vehicle_id: 'v-elw', position: 0 },
		{ vehicle_id: 'v-hlf', position: 1 },
		{ vehicle_id: 'v-mtw', position: 2 },
	]);
	await expect(page.locator('.convoy-vehicle-row').first()).toContainText('ELW 1');
});

test('Planung · Fahrzeugpool: ein Fahrzeug im Verband lässt sich herausnehmen, nicht noch einmal hinzufügen', async ({ page }) => {
	const aufrufe = await planung(page);
	await tab(page, 'Fahrzeuge').click();
	await page.locator('.vehicle-item:not(.convoy-vehicle-row)', { hasText: 'MTW' }).first()
		.click({ button: 'right', position: { x: 8, y: 8 } });
	await expect(menue(page).locator('.titel').first()).toHaveText('MTW · Florian 1/19');
	await expect(menue(page).getByRole('menuitem', { name: /hinzufügen/ })).toHaveCount(0);
	await eintrag(page, 'Aus dem Verband nehmen').click();
	await expect.poll(() => aufrufe.find((a) => a.methode === 'DELETE')?.pfad).toBe(`/api/convoys/${CONVOY}/vehicles/v-mtw`);
});

// ── Org-Admin ──────────────────────────────────────────────────────────

const MITGLIEDER = [
	{ user_id: 'u-anna', email: 'anna@example.org', role: 'beobachter', first_name: 'Anna', last_name: 'Lutz' },
	{ user_id: 'u-ben', email: 'ben@example.org', role: 'planer', first_name: null, last_name: null },
];

async function orgAdmin(page: Page): Promise<Aufruf[]> {
	const aufrufe = await mockApi(page, {
		...GRUNDLAGE,
		[`GET /api/organizations/${ORG}/members`]: MITGLIEDER,
	});
	await page.goto(`/o/${SLUG}/admin`, { waitUntil: 'domcontentloaded' });
	await expect(page.getByRole('cell', { name: 'anna@example.org' })).toBeVisible();
	return aufrufe;
}

test('Org-Admin · Mitglieder: die Rolle steht im Menü und wechselt wie im Auswahlfeld', async ({ page }) => {
	const aufrufe = await orgAdmin(page);
	await page.getByRole('row', { name: /anna@example.org/ }).getByRole('cell', { name: 'anna@example.org' })
		.click({ button: 'right' });
	await expect(menue(page).locator('.titel').first()).toHaveText('Anna Lutz');
	const rolle = (name: string) => menue(page).getByRole('menuitemradio', { name: `Rolle: ${name}` });
	await expect(rolle('Beobachter')).toHaveAttribute('aria-checked', 'true');
	await expect(rolle('Planer')).toHaveAttribute('aria-checked', 'false');

	await rolle('Planer').click();
	await expect.poll(() => aufrufe[0]).toEqual({
		methode: 'PATCH', pfad: `/api/organizations/${ORG}/members/u-anna`, koerper: { role: 'planer' },
	});
});

test('Org-Admin · Mitglieder: dieselbe Rolle noch einmal schickt nichts, Entfernen fragt nach', async ({ page }) => {
	const aufrufe = await orgAdmin(page);
	const ben = page.getByRole('cell', { name: 'ben@example.org' });
	// Ohne Namen steht die E-Mail im Titel.
	await ben.click({ button: 'right' });
	await expect(menue(page).locator('.titel').first()).toHaveText('ben@example.org');
	await menue(page).getByRole('menuitemradio', { name: 'Rolle: Planer' }).click();
	await expect(menue(page)).toHaveCount(0);

	// Wie der ✕-Knopf: erst die Rückfrage. Abgelehnt → kein Aufruf.
	await ben.click({ button: 'right' });
	page.once('dialog', (d) => d.dismiss());
	await eintrag(page, 'Aus der Organisation entfernen').click();
	await ben.click({ button: 'right' });
	page.once('dialog', (d) => d.accept());
	await eintrag(page, 'Aus der Organisation entfernen').click();
	await expect.poll(() => aufrufe).toEqual([
		{ methode: 'DELETE', pfad: `/api/organizations/${ORG}/members/u-ben`, koerper: null },
	]);
});

// ── Admin-Bereich ──────────────────────────────────────────────────────

const BENUTZER = [
	{
		id: 'u-anna', email: 'anna@example.org', first_name: 'Anna', last_name: 'Lutz',
		is_active: true, is_superadmin: false, is_demo: false, mfa_enabled: false,
		created_at: '2026-09-01T08:00:00Z', orgs: [{ id: ORG, name: 'THW OV Musterstadt', role: 'planer' }],
	},
	{
		id: 'u-carl', email: 'carl@example.org', first_name: 'Carl', last_name: 'Meier',
		is_active: false, is_superadmin: false, is_demo: false, mfa_enabled: true,
		created_at: '2026-09-02T08:00:00Z', orgs: [],
	},
];

const ORGS = [
	{ id: ORG, name: 'THW OV Musterstadt', slug: 'thw-musterstadt', owner_id: 'u-anna', owner_email: 'anna@example.org', member_count: 2, is_demo: false },
];

async function adminBereich(page: Page): Promise<Aufruf[]> {
	const aufrufe = await mockApi(page, {
		...GRUNDLAGE,
		'GET /api/admin/users': BENUTZER,
		'GET /api/admin/organizations': ORGS,
	});
	await page.goto('/admin', { waitUntil: 'domcontentloaded' });
	await expect(page.getByRole('cell', { name: 'anna@example.org' })).toBeVisible();
	return aufrufe;
}

test('Admin · Benutzer: Schalter zeigen den Stand, ein Klick schaltet um wie der Knopf', async ({ page }) => {
	const aufrufe = await adminBereich(page);
	await page.getByRole('cell', { name: 'carl@example.org' }).click({ button: 'right' });
	await expect(menue(page).locator('.titel').first()).toHaveText('Carl Meier');
	await expect(menue(page).getByRole('menuitemcheckbox', { name: 'Aktiv' })).toHaveAttribute('aria-checked', 'false');
	await expect(menue(page).getByRole('menuitemcheckbox', { name: 'Superadmin' })).toHaveAttribute('aria-checked', 'false');
	// MFA zurücksetzen nur, wo MFA an ist — hier ja.
	await expect(eintrag(page, 'MFA zurücksetzen')).toBeVisible();
	// Ohne SMTP kein Versand per Mail — gesperrt mit Grund, wie der Knopf.
	await expect(eintrag(page, 'Neues Passwort per E-Mail')).toBeDisabled();
	await expect(eintrag(page, 'Neues Passwort per E-Mail')).toHaveAttribute('title', /SMTP/);

	await menue(page).getByRole('menuitemcheckbox', { name: 'Aktiv' }).click();
	await expect.poll(() => aufrufe[0]).toEqual({
		methode: 'PATCH', pfad: '/api/admin/users/u-carl', koerper: { is_active: true },
	});

	// Anna hat kein MFA: kein Eintrag dafür.
	await page.getByRole('cell', { name: 'anna@example.org' }).click({ button: 'right' });
	await expect(eintrag(page, 'MFA zurücksetzen')).toHaveCount(0);
});

test('Admin · Organisationen: Code und Anmeldelink kopieren', async ({ page, context }) => {
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);
	await adminBereich(page);
	await page.locator('.tab', { hasText: 'Organisationen' }).click();
	const zeile = page.getByRole('cell', { name: 'THW OV Musterstadt' });
	await zeile.click({ button: 'right' });
	await expect(menue(page).locator('.titel').first()).toHaveText('THW OV Musterstadt');
	await eintrag(page, 'Code kopieren').click();
	await expect(page.getByRole('status')).toHaveText('In die Zwischenablage kopiert');
	expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('thw-musterstadt');

	await zeile.click({ button: 'right' });
	await eintrag(page, 'Anmeldelink kopieren').click();
	await expect.poll(() => page.evaluate(() => navigator.clipboard.readText()))
		.toBe('http://localhost:4173/o/thw-musterstadt/login');
});
