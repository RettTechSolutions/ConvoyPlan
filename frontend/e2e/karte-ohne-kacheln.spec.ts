import { test, expect } from '@playwright/test';
import { CONVOY, ELW, GRUNDLAGE, HLF, KONVOI, MTW, SLUG, mockApi } from './kontextmenue-attrappe';

// Ohne Kacheln muss die Karte trotzdem ihre eigenen Ebenen tragen: Route,
// Sperrungen, Regionsmaske. MapLibre feuert `load` erst mit dem ersten Frame,
// in dem alles geladen ist — scheitern alle Kacheln (Kachelserver weg), kommt
// der nie, und eingerichtet wurde vorher in `load`. Die Route fehlte dann, und
// die Karte zoomte nicht einmal auf sie (`$lib/map/stilBereit.ts`).
//
// `mockApi` beantwortet `/api/tiles/**` mit 404 — genau dieser Fall.

const BREITE = 50.6;
const VON = 9.0;
const BIS = 12.5;
const ROUTE = {
	id: 'r1', convoy_id: CONVOY, distance_m: 250_000, duration_s: 10_800, routing_params: {},
	geojson: { type: 'LineString', coordinates: Array.from({ length: 36 }, (_, i) => [VON + i * 0.1, BREITE]) },
	fuel_analysis: null, kanalwechsel: [], durchfahrtshoehen: null, bruecken: null, gewichtsgrenzen: null,
};

test('Scheitern alle Kacheln, zoomt die Karte trotzdem auf die gespeicherte Route', async ({ page }) => {
	await mockApi(page, {
		...GRUNDLAGE,
		'GET /api/vehicles/': [HLF, MTW, ELW],
		'GET /api/convoys/': [KONVOI],
		[`GET /api/convoys/${CONVOY}`]: KONVOI,
		[`GET /api/convoys/${CONVOY}/route`]: ROUTE,
		'GET /api/organizations/': [],
	});
	await page.addInitScript((slug) => localStorage.setItem(`cp_tutorial_seen_v1__${slug}`, '1'), SLUG);
	await page.goto(`/o/${SLUG}/plan`, { waitUntil: 'domcontentloaded' });

	// Die waagerechte Route füllt nach `fitRoute` (Polster 60 px) die Breite der
	// Karte; WP Erfurt (Länge 11.03) steht dann an einer berechenbaren Stelle.
	// Ohne Einrichtung bliebe die Karte auf dem Startausschnitt (Zoom 5,7), und
	// der Marker stünde weit links davon.
	const karte = (await page.locator('.map-area .maplibregl-canvas').boundingBox())!;
	const erwartet = karte.x + 60 + ((11.03 - VON) / (BIS - VON)) * (karte.width - 120);
	const marker = page.locator('.maplibregl-marker', { hasText: 'WP Erfurt' });
	await expect.poll(async () => {
		const b = await marker.boundingBox();
		return b ? Math.abs(b.x + b.width / 2 - erwartet) : Infinity;
	}, { timeout: 10_000 }).toBeLessThan(15);
});
