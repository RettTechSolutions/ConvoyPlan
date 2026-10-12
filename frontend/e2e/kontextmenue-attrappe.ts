import { expect, type Page, type Request } from '@playwright/test';
import { blockExternal } from './fixtures';

/**
 * Planung, Org-Admin und Admin-Bereich in der echten App, mit abgefangener
 * API — für `kontextmenue-planung-und-admin.spec.ts` und für die Bilder im
 * Wiki (`wiki-bilder/`), damit beide dieselbe Lage zeigen.
 */

export const SLUG = 'km-plan';
export const ORG = 'o1';
export const CONVOY = 'c1';

/** Ein schreibender Aufruf, wie er beim Server ankam. */
export type Aufruf = { methode: string; pfad: string; koerper: unknown };

export type Antwort = unknown | ((req: Request) => unknown);

/**
 * Fängt `/api/**` ab: bekannte Pfade bekommen ihre Antwort, unbekannte
 * GET-Aufrufe ein 404 (die Seiten fangen das ab), jeder schreibende Aufruf
 * landet in der Liste und bekommt `{}`.
 */
export async function mockApi(page: Page, antworten: Record<string, Antwort>): Promise<Aufruf[]> {
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
export function ich(req: Request) {
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

export const GRUNDLAGE: Record<string, Antwort> = {
	'GET /api/setup/status': { setup_required: false },
	'GET /api/license/mode': { demo_mode: false },
	'GET /api/auth/me': ich,
};

export const menue = (page: Page) => page.getByRole('menu');
export const eintrag = (page: Page, name: string) => menue(page).getByRole('menuitem', { name, exact: true });

// ── Planung ────────────────────────────────────────────────────────────

export function fahrzeug(id: string, name: string, callsign: string | null, order_index: number) {
	return {
		id, name, callsign, license_plate: null, height_cm: null, weight_kg: null, length_cm: null,
		convoy_role: null, axle_load_kg: null, propulsion: 'combustion',
		tank_capacity_l: null, fuel_consumption_l100km: null, current_fuel_l: null,
		battery_capacity_kwh: null, consumption_kwh_100km: null, current_charge_kwh: null,
		staerke_soll_fuehrer: null, staerke_soll_unterfuehrer: null, staerke_soll_mannschaften: null,
		order_index, range_km: null, range_uses_defaults: false,
	};
}

export const HLF = fahrzeug('v-hlf', 'HLF 20', 'Florian 1/46', 0);
export const MTW = fahrzeug('v-mtw', 'MTW', 'Florian 1/19', 1);
export const ELW = fahrzeug('v-elw', 'ELW 1', null, 2);

export function wegpunkt(id: string, name: string, lat: number, lon: number, order_index: number) {
	return {
		id, name, type: 'waypoint', lat, lon, planned_arrival: null, planned_departure: null,
		hold_duration_min: 0, halt_purpose: null, notes: null, order_index,
	};
}

export function imVerband(v: ReturnType<typeof fahrzeug>, position: number) {
	return {
		vehicle: v, position, vehicle_status: 'planned', status_level: null, status_note: null,
		status_changed_at: null, sonderfunktion: null, mobile_phone: null,
		staerke_soll_fuehrer: null, staerke_soll_unterfuehrer: null, staerke_soll_mannschaften: null,
		staerke_ist_fuehrer: null, staerke_ist_unterfuehrer: null, staerke_ist_mannschaften: null,
	};
}

export const KONVOI = {
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

export async function planung(page: Page): Promise<Aufruf[]> {
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

export const tab = (page: Page, name: string) => page.locator('.tab', { hasText: name }).first();

// ── Org-Admin ──────────────────────────────────────────────────────────

export const MITGLIEDER = [
	{ user_id: 'u-anna', email: 'anna@example.org', role: 'beobachter', first_name: 'Anna', last_name: 'Lutz' },
	{ user_id: 'u-ben', email: 'ben@example.org', role: 'planer', first_name: null, last_name: null },
];

export async function orgAdmin(page: Page): Promise<Aufruf[]> {
	const aufrufe = await mockApi(page, {
		...GRUNDLAGE,
		[`GET /api/organizations/${ORG}/members`]: MITGLIEDER,
	});
	await page.goto(`/o/${SLUG}/admin`, { waitUntil: 'domcontentloaded' });
	await expect(page.getByRole('cell', { name: 'anna@example.org' })).toBeVisible();
	return aufrufe;
}

// ── Admin-Bereich ──────────────────────────────────────────────────────

export const BENUTZER = [
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

export const ORGS = [
	{ id: ORG, name: 'THW OV Musterstadt', slug: 'thw-musterstadt', owner_id: 'u-anna', owner_email: 'anna@example.org', member_count: 2, is_demo: false },
];

export async function adminBereich(page: Page): Promise<Aufruf[]> {
	const aufrufe = await mockApi(page, {
		...GRUNDLAGE,
		'GET /api/admin/users': BENUTZER,
		'GET /api/admin/organizations': ORGS,
	});
	await page.goto('/admin', { waitUntil: 'domcontentloaded' });
	await expect(page.getByRole('cell', { name: 'anna@example.org' })).toBeVisible();
	return aufrufe;
}
