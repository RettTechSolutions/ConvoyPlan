import { test, expect, type Page } from '@playwright/test';
import { blockExternal, fahrzeug, trackPayload } from './fixtures';

/**
 * Abbiegehinweise im Fahrer-Link: das nächste Manöver ab der **eigenen**
 * Position. Beobachter bekommen keines — gegen die Verbandsspitze gerechnet
 * gälte „In 300 m rechts" für das Schlusslicht nicht.
 */

const SLUG = '6dA4KrUG';

// Eine Gerade nach Norden, gut 11 km; ein Breitengrad sind rund 111,2 km.
const GEOJSON = { type: 'LineString', coordinates: [[13.4, 52.5], [13.4, 52.6]] };
const ROUTE_STEPS = [
	{ m: 0, sign: 0, text: 'Losfahren auf Hauptstraße', street_name: 'Hauptstraße', exit_number: null },
	{ m: 5560, sign: 2, text: 'Rechts abbiegen auf Ringstraße', street_name: 'Ringstraße', exit_number: null },
	{ m: 11119, sign: 4, text: 'Ziel erreicht!', street_name: null, exit_number: null },
];

/** Die eigene Position, so viele Meter nach dem Start auf der Geraden. */
function eigenePosition(m: number) {
	return {
		vehicle_id: 'v1', lat: 52.5 + m / 111_195, lon: 13.4,
		speed_kmh: 60, heading: 0, recorded_at: '2026-09-18T14:05:00Z',
	};
}

async function oeffnen(
	page: Page,
	opts: {
		scope: 'track' | 'driver';
		eigenesFahrzeug?: boolean;
		m?: number;
		mitHinweisen?: boolean;
		ohnePosition?: boolean;
	},
) {
	await blockExternal(page);
	await page.route('**/api/track/*', async (route) => {
		await route.fulfill({
			json: {
				...trackPayload(opts.scope, [fahrzeug()], opts.ohnePosition ? [] : [eigenePosition(opts.m ?? 4000)]),
				geojson: GEOJSON,
				...(opts.mitHinweisen === false ? {} : { route_steps: ROUTE_STEPS }),
			},
		});
	});
	if (opts.eigenesFahrzeug) {
		// Genau so kommt ein Fahrer nach dem Neuladen zurück: Das gewählte
		// Fahrzeug steht im sessionStorage.
		await page.addInitScript((slug) => sessionStorage.setItem(`cp-track-driver-${slug}`, 'v1'), SLUG);
	}
	await page.goto(`/track/${SLUG}`, { waitUntil: 'domcontentloaded' });
	await expect(page.getByText('Verlegung Nord').filter({ visible: true }).first()).toBeVisible();
}

test.describe('Abbiegehinweise in der Tracking-Ansicht', () => {
	test('der Fahrer sieht das nächste Manöver ab seiner Position', async ({ page }) => {
		await oeffnen(page, { scope: 'driver', eigenesFahrzeug: true, m: 4000 });

		const hinweis = page.getByTestId('manoever');
		await expect(hinweis).toBeVisible();
		await expect(hinweis).toContainText('In 1,6 km');
		await expect(hinweis).toContainText('Rechts abbiegen auf Ringstraße');
		await expect(hinweis).toContainText('→');
	});

	test('nach der Abzweigung kommt das nächste Manöver', async ({ page }) => {
		await oeffnen(page, { scope: 'driver', eigenesFahrzeug: true, m: 6000 });

		const hinweis = page.getByTestId('manoever');
		// Noch 5,1 km bis zum Ziel: das Ziel wird trotzdem angesagt, nicht nur
		// „Weiter auf …".
		await expect(hinweis).toContainText('Ziel erreicht');
	});

	test('ohne gewähltes Fahrzeug steht kein Manöver da', async ({ page }) => {
		await oeffnen(page, { scope: 'driver', eigenesFahrzeug: false });

		await expect(page.getByTestId('manoever')).toHaveCount(0);
	});

	test('Beobachter bekommen kein Manöver', async ({ page }) => {
		await oeffnen(page, { scope: 'track' });

		await expect(page.getByTestId('manoever')).toHaveCount(0);
	});

	test('eine Instanz ohne Hinweise zeigt keines', async ({ page }) => {
		await oeffnen(page, { scope: 'driver', eigenesFahrzeug: true, mitHinweisen: false });

		await expect(page.getByTestId('manoever')).toHaveCount(0);
	});
});

test.describe('Hinweisliste im Seitenmenü', () => {
	test('Beobachter sehen alle Hinweise mit dem Stand der Spitze', async ({ page }) => {
		await oeffnen(page, { scope: 'track', m: 4000 });
		await page.getByRole('button', { name: 'Route', exact: true }).click();

		const liste = page.getByTestId('hinweisliste');
		const zeilen = liste.getByRole('listitem');
		await expect(zeilen).toHaveCount(3);
		await expect(page.getByText('Stand ab der Verbandsspitze')).toBeVisible();

		// Der Start liegt hinter der Spitze, die Abzweigung ist das Nächste.
		await expect(zeilen.nth(0)).toContainText('passiert');
		const naechste = liste.locator('[aria-current="step"]');
		await expect(naechste).toHaveCount(1);
		await expect(naechste).toContainText('Rechts abbiegen auf Ringstraße');
		await expect(naechste).toContainText('km 5,6');
		await expect(naechste).toContainText('Spitze in 1,6 km');
		await expect(zeilen.nth(2)).toContainText('Ziel erreicht');
		await expect(zeilen.nth(2)).not.toContainText('passiert');
	});

	test('ohne Live-Position steht die Liste ohne Stand da', async ({ page }) => {
		await oeffnen(page, { scope: 'track', ohnePosition: true });
		await page.getByRole('button', { name: 'Route', exact: true }).click();

		await expect(page.getByText('Noch keine Live-Position — ohne Stand')).toBeVisible();
		await expect(page.getByTestId('hinweisliste').getByRole('listitem')).toHaveCount(3);
		await expect(page.getByTestId('hinweisliste').locator('[aria-current="step"]')).toHaveCount(0);
		await expect(page.getByTestId('hinweisliste')).not.toContainText('passiert');
	});

	test('ohne Hinweise gibt es keinen Reiter „Route"', async ({ page }) => {
		await oeffnen(page, { scope: 'track', mitHinweisen: false });

		await expect(page.getByRole('button', { name: 'Fahrzeuge', exact: true })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Route', exact: true })).toHaveCount(0);
	});
});
