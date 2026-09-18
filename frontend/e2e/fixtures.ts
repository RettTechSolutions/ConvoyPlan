import type { Page } from '@playwright/test';

/** Antwort von `GET /api/track/<slug>` für eine geöffnete Ansicht. */
export function trackPayload(scope: 'track' | 'driver') {
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
		vehicles: [
			{
				id: 'v1', name: 'MTW 1', callsign: 'Heros 12/19',
				sonderfunktion: 'Führung', vehicle_status: 'planned', position: 1,
			},
		],
		positions: [],
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
	opts: { scope: 'track' | 'driver'; password?: string },
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
		await route.fulfill({ json: trackPayload(opts.scope) });
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
