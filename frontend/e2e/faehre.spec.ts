import { test, expect } from '@playwright/test';
import { CONVOY, planung, tab } from './kontextmenue-attrappe';

// Fähren im Reiter Route. Die Zusagen:
//  - jede Überfahrt steht mit Kilometer, Länge und Dauer da;
//  - sie sagt, als was sie für die Lenkzeiten zählt — und dass eine Tagesruhe
//    an Bord eine Schlafkabine braucht, denn das weiß die Planung nicht;
//  - eine geschätzte Dauer ist als solche erkennbar;
//  - ohne Fähre steht kein Block da.

function route(faehren: unknown) {
	return {
		id: 'route-1', convoy_id: CONVOY, distance_m: 1_590_000, duration_s: 90_000, routing_params: null,
		kanalwechsel: [], durchfahrtshoehen: [], gewichtsgrenzen: [], bruecken: null, faehren,
		geojson: { type: 'LineString', coordinates: [[9.93, 49.79], [11.03, 50.98], [12.37, 51.34]] },
		fuel_analysis: null,
	};
}

const faehre = (km: number, dauer_s: number, geschaetzt = false) => ({
	km, von_m: km * 1000, bis_m: km * 1000 + 230_000, laenge_km: 230, dauer_s,
	lat: 41.13, lon: 16.87, ziel_lat: 41.31, ziel_lon: 19.45, geschaetzt,
});

const block = (page: import('@playwright/test').Page) => page.getByRole('region', { name: 'Fähren' });

test('Überfahrt mit Dauer und Wertung für die Lenkzeiten', async ({ page }) => {
	await planung(page, {
		[`GET /api/convoys/${CONVOY}/route`]: route([faehre(1252, 9.5 * 3600), faehre(1500, 2 * 3600, true)]),
	});
	await tab(page, 'Route').click();
	const eintraege = block(page).getByRole('listitem');
	await expect(eintraege).toHaveCount(2);
	await expect(eintraege.nth(0)).toContainText('km 1252');
	await expect(eintraege.nth(0)).toContainText('230 km');
	await expect(eintraege.nth(0)).toContainText('9 h 30 min');
	await expect(eintraege.nth(0)).toContainText('zählt als Tagesruhe – nur mit Schlafkabine');
	await expect(eintraege.nth(1)).toContainText('2 h (geschätzt)');
	await expect(eintraege.nth(1)).toContainText('zählt als Lenkpause');
	await expect(block(page)).toContainText('Auf See vergeht Reisezeit, aber keine Lenkzeit.');
	await expect(block(page)).toContainText('mit 25 km/h geschätzt');
	await expect(eintraege.nth(0).getByRole('button', { name: 'Fähre bei km 1252 auf der Karte zeigen' })).toBeVisible();
});

test('ohne Fähre kein Block', async ({ page }) => {
	await planung(page, { [`GET /api/convoys/${CONVOY}/route`]: route([]) });
	await tab(page, 'Route').click();
	await expect(page.getByText('Keine Höhenbeschränkung auf der Strecke bekannt.')).toBeAttached();
	await expect(block(page)).toHaveCount(0);
});
