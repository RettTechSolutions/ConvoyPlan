import { test, expect } from '@playwright/test';
import { CONVOY, planung, tab } from './kontextmenue-attrappe';

// Übernommene Halte nach einer neuen Route. Gemeldet: nach einer Umplanung
// standen die alten Halte, wo sie für die vorherige Route fällig waren, die
// Empfehlung legte neue davor — zwei Tagesruhezeiten 45 km auseinander. Die
// Zusagen an der Oberfläche:
//  - meldet das Backend veraltete Vorschläge, sagt der Reiter Route das und
//    bietet „Halte neu verteilen" an; die Marke am Reiter zählt es mit;
//  - in der Wegpunktliste tragen genau diese Halte „veraltet";
//  - der Knopf verteilt am Server neu und berechnet danach die Route, damit die
//    neuen Halte einsortiert werden — und bleibt dabei im Reiter Route;
//  - ein übernommener Halt trägt seine Herkunft und keinen Kilometer im Namen.

const HALT = {
	stop_km: 126.5, stop_position: { lat: 50.2, lon: 10.4 }, duration_min: 15, kind: 'tech',
	is_rest: false, after_drive_s: 7200, covers_break: false,
};

function route(fuel: Record<string, unknown>) {
	return {
		id: 'route-1', convoy_id: CONVOY, distance_m: 412_000, duration_s: 16_200, routing_params: null,
		kanalwechsel: [], durchfahrtshoehen: [], gewichtsgrenzen: [], bruecken: null,
		geojson: { type: 'LineString', coordinates: [[9.93, 49.79], [11.03, 50.98], [12.37, 51.34]] },
		fuel_analysis: {
			vehicles_with_range: [], min_range_km: null, route_distance_km: 412, fuel_stop_needed: false,
			fuel_stop_km: null, fuel_stop_position: null, limiting_vehicle: null, has_default_values: false,
			vehicles_without_data: 0, recommended_stop_duration_min: null, duration_halt_needed: false,
			duration_halts: [], zusammengelegt: [], neu_verteilen: null, rest_needed: false,
			...fuel,
		},
	};
}

test('veraltete Halte: Hinweis, Marke in der Liste, Neuverteilen mit anschließender Berechnung', async ({ page }) => {
	const aufrufe = await planung(page, {
		[`GET /api/convoys/${CONVOY}/route`]: route({ neu_verteilen: { veraltet: ['wp-erfurt'], neu: 2 } }),
		[`POST /api/convoys/${CONVOY}/halte/neu-verteilen`]: { entfernt: 1, hinzugefuegt: 2 },
		[`POST /api/convoys/${CONVOY}/calculate-route`]: route({}),
	});

	// Einmal gezählt, nicht je veraltetem Halt.
	await expect(tab(page, 'Route').locator('.marke')).toHaveText('1');

	await tab(page, 'Wegpunkte').click();
	const zeile = (name: string) => page.locator('.wp-item', { hasText: name });
	await expect(zeile('WP Erfurt').getByText('veraltet', { exact: true })).toBeVisible();
	await expect(zeile('WP Fulda').getByText('veraltet', { exact: true })).toHaveCount(0);

	await tab(page, 'Route').click();
	const hinweis = page.getByRole('status').filter({ hasText: 'Übernommene Halte passen nicht mehr zur Route' });
	await expect(hinweis).toContainText('1 übernommener Halt liegt');
	await expect(hinweis).toContainText('durch die aktuelle Empfehlung (2 Halte)');

	await hinweis.getByRole('button', { name: 'Halte neu verteilen' }).click();
	// Brücken- und Sperrungssuche laufen nach jeder Berechnung nebenher; hier zählt die Folge der beiden.
	const relevant = /\/(halte\/neu-verteilen|calculate-route)$/;
	await expect.poll(() => aufrufe.filter((a) => relevant.test(a.pfad)).map((a) => `${a.methode} ${a.pfad}`)).toEqual([
		`POST /api/convoys/${CONVOY}/halte/neu-verteilen`,
		`POST /api/convoys/${CONVOY}/calculate-route`,
	]);
	await expect(hinweis).toHaveCount(0);
	await expect(tab(page, 'Route')).toHaveClass(/active/);
});

test('„+ Halt" übernimmt mit Herkunft und ohne Kilometer im Namen', async ({ page }) => {
	const aufrufe = await planung(page, {
		[`GET /api/convoys/${CONVOY}/route`]: route({ duration_halt_needed: true, duration_halts: [HALT] }),
	});
	await tab(page, 'Route').click();
	await page.getByRole('button', { name: '+ Halt' }).click();
	await expect.poll(() => aufrufe.find((a) => a.pfad === `/api/convoys/${CONVOY}/waypoints`)).toBeTruthy();
	const koerper = aufrufe.find((a) => a.pfad === `/api/convoys/${CONVOY}/waypoints`)!.koerper as Record<string, unknown>;
	expect(koerper).toMatchObject({
		name: 'Technischer Halt', type: 'technical_stop', vorschlag_art: 'tech', pending_placement: true,
		hold_duration_min: 15, lat: 50.2, lon: 10.4,
	});
});
