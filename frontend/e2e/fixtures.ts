import type { Page } from '@playwright/test';

/** Ein Fahrzeug, wie die Tracking-Nutzlast es führt. */
export type TrackFahrzeug = {
	id: string;
	name: string;
	callsign: string | null;
	sonderfunktion: string | null;
	vehicle_status: string;
	position: number;
	staerke_soll_fuehrer: number | null;
	staerke_soll_unterfuehrer: number | null;
	staerke_soll_mannschaften: number | null;
	staerke_ist_fuehrer: number | null;
	staerke_ist_unterfuehrer: number | null;
	staerke_ist_mannschaften: number | null;
	propulsion?: string;
	tank_capacity_l?: number | null;
	fuel_consumption_l100km?: number | null;
	betriebsstoff_verbrauch?: number | null;
	betriebsstoff_tank?: number | null;
	betriebsstoff_fuellstand?: number | null;
};

/** Ein Fahrzeug ohne jede Stärkeangabe — der Normalfall vor der ersten Meldung. */
export function fahrzeug(teil: Partial<TrackFahrzeug> = {}): TrackFahrzeug {
	return {
		id: 'v1', name: 'MTW 1', callsign: 'Heros 12/19',
		sonderfunktion: 'Führung', vehicle_status: 'planned', position: 1,
		staerke_soll_fuehrer: null, staerke_soll_unterfuehrer: null, staerke_soll_mannschaften: null,
		staerke_ist_fuehrer: null, staerke_ist_unterfuehrer: null, staerke_ist_mannschaften: null,
		...teil,
	};
}

/**
 * Eine gemeldete Position — daran erkennt die Fahrzeugliste ein Fahrzeug als
 * „LIVE". Beide Ansichten führen dieselben Felder (`TrackPosition` bzw.
 * `VehiclePosition`).
 */
export function position(fahrzeugId = 'v1') {
	return {
		vehicle_id: fahrzeugId, lat: 52.5, lon: 13.4,
		speed_kmh: 42, heading: 90, recorded_at: '2026-09-18T14:05:00Z',
	};
}

/** Antwort von `GET /api/track/<slug>` für eine geöffnete Ansicht. */
export function trackPayload(
	scope: 'track' | 'driver',
	fahrzeuge?: TrackFahrzeug[],
	positionen?: ReturnType<typeof position>[],
) {
	return {
		name: 'Verlegung Nord',
		organization: 'THW OV Musterstadt',
		start_time: '2026-09-18T14:00:00Z',
		scope,
		waypoints: [
			{
				name: 'Start Unterkunft', type: 'start', lat: 52.5, lon: 13.4,
				planned_arrival: null, planned_departure: '2026-09-18T14:00:00Z', halt_purpose: null,
			},
		],
		geojson: null,
		distance_m: 42000,
		kanalwechsel: [],
		vehicles: fahrzeuge ?? [fahrzeug()],
		positions: positionen ?? [],
	};
}

/**
 * Bricht alles ab, was nicht von der Testinstanz kommt — Kartenkacheln und
 * Schriften. Ohne das hängt `page.goto` am `load`-Ereignis, sobald der Rechner
 * kein Netz hat, und die Tests wären von fremden Servern abhängig.
 */
export async function blockExternal(page: Page) {
	await page.route('**/*', async (route) => {
		const url = new URL(route.request().url());
		const intern = url.hostname === 'localhost' || url.protocol === 'data:' || url.protocol === 'blob:';
		if (intern) await route.fallback();
		else await route.abort();
	});
}

/**
 * Fängt die Tracking-API ab. Ohne `password` antwortet der Endpunkt sofort mit
 * der Nutzlast; mit Passwort erst die Schranke und nach `POST …/auth` ein Token
 * — genau daran erkennt die Ansicht, dass der Link geschützt ist.
 */
export async function mockTrack(
	page: Page,
	opts: {
		scope: 'track' | 'driver';
		password?: string;
		fahrzeuge?: TrackFahrzeug[];
		positionen?: ReturnType<typeof position>[];
	},
) {
	let freigeschaltet = !opts.password;

	await page.route('**/api/track/*/auth', async (route) => {
		const { password } = JSON.parse(route.request().postData() ?? '{}');
		if (password === opts.password) {
			freigeschaltet = true;
			await route.fulfill({ json: { token: 'test-sitzungstoken' } });
		} else {
			await route.fulfill({ status: 401, json: { detail: 'Falsches Passwort' } });
		}
	});

	await page.route('**/api/track/*', async (route) => {
		if (!freigeschaltet) {
			await route.fulfill({
				json: { requires_password: true, convoy_name: 'Verlegung Nord', scope: opts.scope },
			});
			return;
		}
		await route.fulfill({ json: trackPayload(opts.scope, opts.fahrzeuge, opts.positionen) });
	});
}

/**
 * Ersetzt `window.print`, damit der Testlauf nicht am Druckdialog hängen
 * bleibt, und zählt die Aufrufe mit.
 */
export async function stubPrint(page: Page) {
	await page.addInitScript(() => {
		(window as unknown as { __printAufrufe: number }).__printAufrufe = 0;
		window.print = () => {
			(window as unknown as { __printAufrufe: number }).__printAufrufe++;
		};
	});
}

export function printAufrufe(page: Page) {
	return page.evaluate(() => (window as unknown as { __printAufrufe: number }).__printAufrufe);
}

/** Liest den Inhalt eines QR-Codes aus dem angezeigten Bild zurück. */
export async function qrInhalt(page: Page, bildSelektor: string): Promise<string> {
	return page.evaluate(async (selektor) => {
		const img = document.querySelector(selektor) as HTMLImageElement | null;
		if (!img) throw new Error(`Kein QR-Bild unter ${selektor}`);
		if (!img.complete) await new Promise((r) => img.addEventListener('load', r, { once: true }));

		const canvas = document.createElement('canvas');
		canvas.width = img.naturalWidth;
		canvas.height = img.naturalHeight;
		const ctx = canvas.getContext('2d')!;
		ctx.drawImage(img, 0, 0);
		const daten = ctx.getImageData(0, 0, canvas.width, canvas.height);

		const jsQR = (window as unknown as { jsQR: (d: Uint8ClampedArray, w: number, h: number) => { data: string } | null }).jsQR;
		const treffer = jsQR(daten.data, daten.width, daten.height);
		if (!treffer) throw new Error('QR-Code nicht lesbar');
		return treffer.data;
	}, bildSelektor);
}

/** Ein Fahrzeug im Verband, wie `GET /api/convoys/<id>` es führt. */
export function konvoiFahrzeug(teil: Record<string, unknown> = {}) {
	const { vehicle, ...rest } = teil as { vehicle?: Record<string, unknown> };
	return {
		position: 1,
		vehicle_status: 'planned',
		status_level: null,
		status_note: null,
		staerke_soll_fuehrer: null,
		staerke_soll_unterfuehrer: null,
		staerke_soll_mannschaften: null,
		staerke_ist_fuehrer: null,
		staerke_ist_unterfuehrer: null,
		staerke_ist_mannschaften: null,
		staerke_gemeldet_at: null,
		...rest,
		vehicle: { id: 'v1', name: 'MTW 1', callsign: 'Heros 12/19', ...(vehicle ?? {}) },
	};
}

/** Ein Marschverband, wie `GET /api/convoys/<id>` ihn liefert. */
export function convoyPayload(id: string, fahrzeuge?: ReturnType<typeof konvoiFahrzeug>[]) {
	return {
		id,
		name: 'Verlegung Nord',
		organization: 'THW OV Musterstadt',
		start_time: '2026-09-18T14:00:00Z',
		waypoints: [],
		convoy_vehicles: fahrzeuge ?? [konvoiFahrzeug()],
	};
}

/** Eine abgefangene Stärkemeldung aus `PATCH …/vehicles/<id>/staerke`. */
/** Was an `PATCH …/betriebsstoff` ging — samt dem Fahrzeug aus dem Pfad. */
export type BetriebsstoffMeldung = {
	fahrzeugId: string;
	verbrauch: number | null;
	tank: number | null;
	fuellstand: number | null;
};

export type StaerkeMeldung = {
	fahrzeugId: string;
	fuehrer: number;
	unterfuehrer: number;
	mannschaften: number;
};

/**
 * Das Org-Portal mit der Kernregel des Backends: **welche Sitzung gilt,
 * entscheidet der `X-Org-Slug`-Kopf.** Fehlt er, zählt die organisationslose
 * (Superadmin-)Sitzung — die ist eine gültige Anmeldung, kommt aber an keine
 * Organisationsdaten heran und bekommt dort 403 „Org context required"
 * (`deps.get_org_context`). Genau dieser Unterschied macht eine Anfrage ohne
 * Kopf im Test sichtbar, statt sie stillschweigend gelingen zu lassen.
 */
export async function mockOrgPortal(
	page: Page,
	opts: {
		slug: string;
		convoyId: string;
		fahrzeuge?: ReturnType<typeof konvoiFahrzeug>[];
		/** Schon gemeldete Positionen — die Liste zeigt diese Fahrzeuge als „LIVE". */
		positionen?: ReturnType<typeof position>[];
		/** Rolle der angemeldeten Sitzung. Unter `fahrer` darf nichts gemeldet werden. */
		rolle?: 'beobachter' | 'fahrer' | 'planer' | 'admin';
		/**
		 * Wohin nachgetragene Betriebsstoffmeldungen (`PATCH …/betriebsstoff`)
		 * geschrieben werden. Eine eigene Liste statt eines zweiten
		 * Rückgabewerts, damit die bestehenden Aufrufer bleiben, wie sie sind.
		 */
		betriebsstoffMeldungen?: BetriebsstoffMeldung[];
	},
): Promise<StaerkeMeldung[]> {
	// Was an `PATCH …/staerke` hinausging — die Liste wächst im Test mit.
	const staerkeMeldungen: StaerkeMeldung[] = [];
	const orgKopf = (route: Parameters<Parameters<Page['route']>[1]>[0]) =>
		route.request().headers()['x-org-slug'] ?? null;

	await page.route('**/api/setup/status', (route) => route.fulfill({ json: { setup_required: false } }));
	await page.route('**/api/license/mode', (route) => route.fulfill({ json: { demo_mode: false } }));
	await page.route('**/api/branding**', (route) => route.fulfill({ json: {} }));
	await page.route('**/api/auth/stream-ticket', (route) => route.fulfill({ json: { ticket: 'test-ticket' } }));

	await page.route('**/api/auth/me', (route) => {
		if (orgKopf(route) !== opts.slug) {
			// Die globale Sitzung: angemeldet, aber ohne Organisation.
			route.fulfill({
				json: {
					user_id: 'u1', email: 'super@example.org', is_superadmin: true,
					org_id: null, org_slug: null, org_name: null, role: null, is_demo: false,
				},
			});
			return;
		}
		route.fulfill({
			json: {
				user_id: 'u2', email: 'planer@example.org', is_superadmin: false,
				org_id: 'o1', org_slug: opts.slug, org_name: 'THW OV Musterstadt',
				role: opts.rolle ?? 'planer', is_demo: false,
			},
		});
	});

	await page.route(`**/api/convoys/${opts.convoyId}**`, (route) => {
		if (orgKopf(route) !== opts.slug) {
			route.fulfill({ status: 403, json: { detail: 'Org context required' } });
			return;
		}
		const pfad = new URL(route.request().url()).pathname;
		if (pfad.endsWith('/route')) return void route.fulfill({ json: null });
		if (pfad.endsWith('/positions')) return void route.fulfill({ json: opts.positionen ?? [] });
		if (pfad.endsWith('/betriebsstoff')) {
			const fahrzeugId = pfad.split('/vehicles/')[1]!.replace('/betriebsstoff', '');
			const lage = JSON.parse(route.request().postData() ?? '{}');
			opts.betriebsstoffMeldungen?.push({ fahrzeugId, ...lage });
			return void route.fulfill({ json: { status: 'ok', gemeldet_at: '2026-09-23T06:00:00+00:00' } });
		}
		if (pfad.endsWith('/staerke')) {
			const fahrzeugId = pfad.split('/vehicles/')[1]!.replace('/staerke', '');
			const werte = JSON.parse(route.request().postData() ?? '{}');
			staerkeMeldungen.push({ fahrzeugId, ...werte });
			const gesamt = (werte.fuehrer ?? 0) + (werte.unterfuehrer ?? 0) + (werte.mannschaften ?? 0);
			return void route.fulfill({ json: { status: 'ok', gesamt } });
		}
		route.fulfill({ json: convoyPayload(opts.convoyId, opts.fahrzeuge) });
	});

	return staerkeMeldungen;
}
