import { test, expect, type Page } from '@playwright/test';
import { blockExternal, mockTrack, trackPayload } from './fixtures';

// Ein Neuladen sprang auf den ersten Reiter zurück — wer im Zeitplan stand,
// musste ihn nach jedem Reload wieder suchen. Der Reiter steht seitdem im
// `sessionStorage` (`$lib/reiter-merken.svelte.ts`), für alle Seiten mit Reitern.
//
// Geprüft am Fahrer-Link, weil er dort zwei Fallen hat: Der Zeitplan-Reiter
// gibt es erst mit den Daten (vorher fiel ein gemerkter Reiter sofort zurück),
// und die Adresse landet im QR-Code — der Reiter darf sie nicht verändern.

const SLUG = 'rEiTeRmErKeN';

async function oeffnen(page: Page) {
	await page.routeWebSocket(/\/api\/ws\/track\//, () => {});
	await blockExternal(page);
	await mockTrack(page, { scope: 'track' });
	// Nach `mockTrack` angelegt, deshalb vorrangig: eine Nutzlast mit Zeitplan.
	await page.route('**/api/track/*', async (route) => {
		const nutzlast = trackPayload('track');
		nutzlast.waypoints = [
			...nutzlast.waypoints,
			{
				name: 'Rastplatz', type: 'rest', lat: 52.9, lon: 13.5,
				planned_arrival: '2026-09-18T15:00:00Z', planned_departure: '2026-09-18T15:30:00Z', halt_purpose: null,
			},
		];
		await route.fulfill({ json: nutzlast });
	});
	await page.goto(`/track/${SLUG}`, { waitUntil: 'domcontentloaded' });
}

const reiter = (page: Page, name: string) => page.locator('.tabs .tab', { hasText: name });

test('der gewählte Reiter bleibt nach dem Neuladen offen', async ({ page }) => {
	await oeffnen(page);
	await expect(reiter(page, 'Fahrzeuge')).toHaveClass(/active/);

	await reiter(page, 'Zeitplan').click();
	await expect(reiter(page, 'Zeitplan')).toHaveClass(/active/);

	await page.reload({ waitUntil: 'domcontentloaded' });
	await expect(reiter(page, 'Zeitplan')).toHaveClass(/active/);
	await expect(reiter(page, 'Fahrzeuge')).not.toHaveClass(/active/);

	// Nichts davon in der Adresse — sie ist der geteilte Link.
	expect(new URL(page.url()).pathname).toBe(`/track/${SLUG}`);
	expect(new URL(page.url()).search).toBe('');
	expect(new URL(page.url()).hash).toBe('');
});

test('ein neuer Browser-Tab beginnt beim ersten Reiter', async ({ page, context }) => {
	await oeffnen(page);
	await reiter(page, 'Zeitplan').click();
	await expect(reiter(page, 'Zeitplan')).toHaveClass(/active/);

	const zweite = await context.newPage();
	await oeffnen(zweite);
	await expect(reiter(zweite, 'Zeitplan')).toBeVisible();
	await expect(reiter(zweite, 'Fahrzeuge')).toHaveClass(/active/);
});
