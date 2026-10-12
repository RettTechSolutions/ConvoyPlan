import { test, expect, type Page, type WebSocketRoute } from '@playwright/test';
import { blockExternal, fahrzeug, konvoiFahrzeug, mockOrgPortal, mockTrack, position } from './fixtures';

// Sendet ein fester Tracker für ein Fahrzeug, gehört ihm die Position
// (`$lib/tracking/positionsquelle`). Gemeldet war: KdoW mit aktivem Tracker
// gewählt, „GPS senden" ließ sich trotzdem drücken — der Server verwarf jeden
// Punkt, und der eigene Marker überdeckte lokal den des Trackers. Status und
// Meldungen bleiben am Telefon; nur das Senden der Position nicht.

const SLUG = 'tRaCkErVoRrAnG';

const KDOW = fahrzeug({ id: 'v1', name: 'KdoW', callsign: 'Akkon Pei 10/1' });
const ELW = fahrzeug({ id: 'v2', name: 'ELW 1', callsign: 'Demo 10/1', position: 2 });

const vorSekunden = (s: number) => new Date(Date.now() - s * 1000).toISOString();

async function oeffnen(
	page: Page,
	opts: { fahrzeuge?: ReturnType<typeof fahrzeug>[]; positionen?: ReturnType<typeof position>[] } = {},
) {
	const gesendet: Record<string, unknown>[] = [];
	let verbindung: WebSocketRoute | null = null;
	await page.context().grantPermissions(['geolocation']);
	await page.context().setGeolocation({ latitude: 50.15, longitude: 8.66 });
	await page.routeWebSocket(/\/api\/ws\/track\//, (ws) => {
		verbindung = ws;
		ws.onMessage((roh) => gesendet.push(JSON.parse(String(roh))));
		ws.send(JSON.stringify({ type: 'belegungen', vehicle_ids: [] }));
	});
	await blockExternal(page);
	await mockTrack(page, { scope: 'driver', fahrzeuge: opts.fahrzeuge ?? [KDOW, ELW], positionen: opts.positionen });
	await page.goto(`/track/${SLUG}`, { waitUntil: 'domcontentloaded' });
	await expect.poll(() => verbindung !== null).toBe(true);
	return {
		gesendet: () => gesendet,
		senden: (n: unknown) => verbindung!.send(JSON.stringify(n)),
	};
}

const waehler = (page: Page) => page.getByLabel('Fahrzeug');
const sendenKnopf = (page: Page) => page.getByRole('button', { name: /GPS senden|Manuell setzen/ });
const hinweis = (page: Page) => page.getByText('Die Position kommt vom Fahrzeugtracker.', { exact: false });

test.describe('Tracker hat Vorrang am Fahrer-Link', () => {
	test('sendet der Tracker, gibt es für dieses Fahrzeug kein „GPS senden"', async ({ page }) => {
		await oeffnen(page, { positionen: [position('v1', { quelle: 'tracker', recorded_at: vorSekunden(20) })] });

		await waehler(page).selectOption('v1');
		await expect(sendenKnopf(page)).toBeDisabled();
		await expect(hinweis(page)).toBeVisible();

		// Ein anderes Fahrzeug ohne Tracker sendet wie bisher.
		await waehler(page).selectOption('v2');
		await expect(sendenKnopf(page)).toBeEnabled();
		await expect(hinweis(page)).toHaveCount(0);
	});

	test('schweigt der Tracker länger als fünf Minuten, gilt wieder das Telefon', async ({ page }) => {
		await oeffnen(page, { positionen: [position('v1', { quelle: 'tracker', recorded_at: vorSekunden(6 * 60) })] });

		await waehler(page).selectOption('v1');
		await expect(sendenKnopf(page)).toBeEnabled();
	});

	test('hat die Führung den Tracker übersteuert, sendet das Telefon', async ({ page }) => {
		await oeffnen(page, {
			fahrzeuge: [{ ...KDOW, tracker_uebersteuert_at: vorSekunden(60) }, ELW],
			positionen: [position('v1', { quelle: 'tracker', recorded_at: vorSekunden(20) })],
		});

		await waehler(page).selectOption('v1');
		await expect(sendenKnopf(page)).toBeEnabled();
	});

	test('übernimmt der Tracker während des Sendens, endet das Senden', async ({ page }) => {
		const gegen = await oeffnen(page);
		await waehler(page).selectOption('v1');
		await sendenKnopf(page).click();
		await expect(page.getByRole('button', { name: /Senden stoppen/ })).toBeVisible();

		gegen.senden({ type: 'position', vehicle_id: 'v1', lat: 50.16, lon: 8.67, speed_kmh: 30, heading: 0, quelle: 'tracker' });

		await expect(page.getByRole('button', { name: /Senden stoppen/ })).toHaveCount(0);
		await expect(sendenKnopf(page)).toBeDisabled();
		await expect(hinweis(page)).toBeVisible();
	});

	test('lehnt der Server die Position ab, endet das Senden auch ohne Trackerpunkt', async ({ page }) => {
		const gegen = await oeffnen(page);
		await waehler(page).selectOption('v1');
		await sendenKnopf(page).click();
		await expect(page.getByRole('button', { name: /Senden stoppen/ })).toBeVisible();

		gegen.senden({ type: 'position_abgelehnt', vehicle_id: 'v1', grund: 'tracker' });

		await expect(page.getByRole('button', { name: /Senden stoppen/ })).toHaveCount(0);
		await expect(hinweis(page)).toBeVisible();
	});
});

// Dieselbe Regel in der angemeldeten Tracking-Ansicht — dort war es gemeldet.
// Zusätzlich: Endet das Senden, weil der Tracker übernommen hat, bleibt seine
// Position stehen. „Senden stoppen" löschte sonst die gespeicherte Position,
// und die gehörte in diesem Moment dem Tracker.
test.describe('Tracker hat Vorrang in der Tracking-Ansicht', () => {
	const ORG = 'vorrang-org';
	const CONVOY = 'c-vorrang';

	async function oeffnenAngemeldet(page: Page, positionen: ReturnType<typeof position>[] = []) {
		let kanal: WebSocketRoute | null = null;
		const geloescht: string[] = [];
		await page.context().grantPermissions(['geolocation']);
		await page.context().setGeolocation({ latitude: 50.15, longitude: 8.66 });
		await blockExternal(page);
		await page.routeWebSocket(/\/api\/ws\//, (ws) => { kanal = ws; ws.onMessage(() => {}); });
		await mockOrgPortal(page, {
			slug: ORG, convoyId: CONVOY, rolle: 'planer',
			fahrzeuge: [
				konvoiFahrzeug({ position: 1, vehicle_status: 'en_route', vehicle: { id: 'v1', name: 'KDOW', callsign: 'Akkon Pei 10/1' } }),
				konvoiFahrzeug({ position: 2, vehicle_status: 'en_route', vehicle: { id: 'v2', name: 'ELW 1', callsign: 'Demo 10/1' } }),
			],
			positionen,
		});
		await page.route(`**/api/convoys/${CONVOY}/vehicles/*/position**`, (route) => {
			if (route.request().method() === 'DELETE') geloescht.push(route.request().url());
			return route.fulfill({ json: { status: 'ok' } });
		});
		await page.goto(`/o/${ORG}/tracking/${CONVOY}`, { waitUntil: 'domcontentloaded' });
		await expect.poll(() => kanal !== null).toBe(true);
		return { kanal: () => kanal!, geloescht: () => geloescht };
	}

	const auswahl = (page: Page) => page.getByLabel('Meine Position');

	test('sendet der Tracker, gibt es kein „GPS senden"', async ({ page }) => {
		await oeffnenAngemeldet(page, [position('v1', { quelle: 'tracker', recorded_at: vorSekunden(20) })]);

		await auswahl(page).selectOption('v1');
		await expect(sendenKnopf(page)).toBeDisabled();
		await expect(page.getByTestId('tracker-haelt-position')).toBeVisible();

		await auswahl(page).selectOption('v2');
		await expect(sendenKnopf(page)).toBeEnabled();
	});

	test('übernimmt der Tracker, endet das Senden — seine Position bleibt', async ({ page }) => {
		const { kanal, geloescht } = await oeffnenAngemeldet(page);
		await auswahl(page).selectOption('v1');
		await sendenKnopf(page).click();
		await expect(page.getByRole('button', { name: /Senden stoppen/ })).toBeVisible();

		kanal().send(JSON.stringify({
			type: 'position', vehicle_id: 'v1', lat: 50.16, lon: 8.67, speed_kmh: 30, heading: 0, quelle: 'tracker',
		}));

		await expect(page.getByRole('button', { name: /Senden stoppen/ })).toHaveCount(0);
		await expect(sendenKnopf(page)).toBeDisabled();
		expect(geloescht()).toEqual([]);
	});
});
