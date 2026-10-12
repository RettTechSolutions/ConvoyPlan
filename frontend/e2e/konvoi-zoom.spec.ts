import { test, expect, type Page } from '@playwright/test';
import { blockExternal, fahrzeug, mockTrack, position } from './fixtures';

// „Konvoi" zoomt auf alle Fahrzeuge, die gerade senden. Eine liegengebliebene
// Position zählt nicht mit: ein Fahrzeug, das seit Stunden nicht mehr sendet,
// zöge den Ausschnitt sonst quer durchs Land, und vom Konvoi bliebe ein Punkt.

const jetzt = () => new Date().toISOString();
const MTW = fahrzeug({ id: 'v1', name: 'MTW 1' });
const LKW = fahrzeug({ id: 'v2', name: 'LKW 2', callsign: 'Heros 12/52', position: 2 });
const ALT = fahrzeug({ id: 'v3', name: 'GKW 3', callsign: 'Heros 12/22', position: 3 });

/** Liegt der Marker (beschriftet mit dem Funkrufnamen) im sichtbaren Kartenbereich? */
async function sichtbar(page: Page, rufname: string): Promise<boolean> {
	const karte = await page.locator('.maplibregl-canvas').boundingBox();
	const marker = await page.locator('.maplibregl-marker', { hasText: rufname }).boundingBox();
	if (!karte || !marker) return false;
	const x = marker.x + marker.width / 2;
	const y = marker.y + marker.height / 2;
	return x >= karte.x && x <= karte.x + karte.width && y >= karte.y && y <= karte.y + karte.height;
}

test('Konvoi zoomt auf die sendenden Fahrzeuge, nicht auf liegengebliebene', async ({ page }) => {
	await blockExternal(page);
	await mockTrack(page, {
		scope: 'track',
		fahrzeuge: [MTW, LKW, ALT],
		positionen: [
			// Zwei Fahrzeuge rund 10 km auseinander auf der A9, gerade gemeldet …
			{ ...position('v1'), lat: 48.30, lon: 11.62, recorded_at: jetzt() },
			{ ...position('v2'), lat: 48.38, lon: 11.56, recorded_at: jetzt() },
			// … und eines, das in Hamburg schon lange nicht mehr sendet.
			{ ...position('v3'), lat: 53.55, lon: 10.0, recorded_at: '2026-01-01T08:00:00Z' },
		],
	});
	await page.goto('/track/kOnVoIzOoM', { waitUntil: 'domcontentloaded' });

	await page.getByRole('button', { name: /Konvoi/ }).click();

	await expect.poll(() => sichtbar(page, 'Heros 12/19')).toBe(true);
	await expect.poll(() => sichtbar(page, 'Heros 12/52')).toBe(true);
	// Eng genug, dass Hamburg draußen bleibt — sonst wäre es nur „alles zeigen".
	await expect.poll(() => sichtbar(page, 'Heros 12/22')).toBe(false);
});

test('ohne Position gibt es keinen Konvoi-Knopf', async ({ page }) => {
	await blockExternal(page);
	await mockTrack(page, { scope: 'track', fahrzeuge: [MTW] });
	await page.goto('/track/kOnVoIzOoM', { waitUntil: 'domcontentloaded' });

	await expect(page.locator('.maplibregl-canvas')).toBeVisible();
	await expect(page.getByRole('button', { name: /Konvoi/ })).toHaveCount(0);
});
