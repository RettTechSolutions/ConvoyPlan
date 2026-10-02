import { test, expect, type Page } from '@playwright/test';
import { blockExternal, fahrzeug, mockTrack } from './fixtures';

// Am Fahrer-Link sendet das Handy nur, solange der Bildschirm an ist — mobile
// Browser stellen die Ortung im Hintergrund ein. Die Bildschirmsperre hält ihn
// an; aber der Browser gibt sie selbst frei, sobald die Seite einmal verdeckt
// war (App-Wechsel, Anruf), und holt sie nicht zurück. Ohne erneute Anforderung
// geht das Display in der Halterung danach aus, und mit ihm die Positionen.
//
// Die Sperre ist gestellt: Der Test zählt die Anforderungen und gibt sie frei,
// wie es der Browser beim Verstecken der Seite täte.

const SLUG = 'wAcHbLeIbEn';

async function oeffnen(page: Page) {
	await page.addInitScript(() => {
		const w = window as unknown as {
			__sperren: number;
			__freigeben: () => void;
		};
		w.__sperren = 0;
		let aktiv: EventTarget | null = null;
		w.__freigeben = () => {
			const s = aktiv;
			aktiv = null;
			s?.dispatchEvent(new Event('release'));
		};
		Object.defineProperty(navigator, 'wakeLock', {
			configurable: true,
			value: {
				request: async () => {
					w.__sperren += 1;
					const s = new EventTarget() as EventTarget & { release: () => Promise<void> };
					s.release = async () => {
						if (aktiv === s) w.__freigeben();
					};
					aktiv = s;
					return s;
				},
			},
		});
	});
	await page.context().grantPermissions(['geolocation']);
	await page.context().setGeolocation({ latitude: 51.05, longitude: 13.74 });
	await page.routeWebSocket(/\/api\/ws\/track\//, (ws) => {
		ws.send(JSON.stringify({ type: 'belegungen', vehicle_ids: [] }));
	});
	await blockExternal(page);
	await mockTrack(page, { scope: 'driver', fahrzeuge: [fahrzeug({ id: 'v1', name: 'KdoW' })] });
	await page.goto(`/track/${SLUG}`, { waitUntil: 'domcontentloaded' });
}

const sperren = (page: Page) => page.evaluate(() => (window as unknown as { __sperren: number }).__sperren);

/** Was der Browser beim Verstecken und Wiederzeigen der Seite tut. */
async function verdeckenUndZurueck(page: Page) {
	await page.evaluate(() => {
		(window as unknown as { __freigeben: () => void }).__freigeben();
		document.dispatchEvent(new Event('visibilitychange'));
	});
}

test.describe('Bildschirm am Fahrer-Link', () => {
	test('nach einem App-Wechsel hält die Seite den Bildschirm wieder an', async ({ page }) => {
		await oeffnen(page);
		await page.getByLabel('Fahrzeug').selectOption('v1');
		await page.getByRole('button', { name: /GPS senden/ }).click();
		await expect.poll(() => sperren(page)).toBe(1);

		await verdeckenUndZurueck(page);

		await expect.poll(() => sperren(page)).toBe(2);
	});

	test('wer nicht sendet, hält den Bildschirm nicht an', async ({ page }) => {
		await oeffnen(page);
		await page.getByLabel('Fahrzeug').selectOption('v1');
		await page.getByRole('button', { name: /GPS senden/ }).click();
		await expect.poll(() => sperren(page)).toBe(1);
		await page.getByRole('button', { name: /Senden stoppen/ }).click();

		await verdeckenUndZurueck(page);

		// Kurz warten, damit eine fälschliche Anforderung auch ankäme.
		await page.waitForTimeout(300);
		expect(await sperren(page)).toBe(1);
	});
});
