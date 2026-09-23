import { test, expect, type Page, type WebSocketRoute } from '@playwright/test';
import { blockExternal, fahrzeug, mockTrack, position } from './fixtures';

// Ein Fahrzeug sendet von genau einem Gerät. Gemeldet war: KdoW in der App
// gewählt — und im Browser ließ er sich noch einmal wählen. Die Belegung führt
// der Server; hier steht, was der Fahrer-Link daraus macht. Die Gegenstelle ist
// gestellt: sie hört mit und antwortet, was der Server antworten würde.

const SLUG = 'bElEgUnG';

const KDOW = fahrzeug({ id: 'v1', name: 'KdoW', callsign: 'Florian 10' });
const ELW = fahrzeug({ id: 'v2', name: 'ELW 1', callsign: 'Florian 11', position: 2 });

interface Gegenstelle {
	gesendet: () => Record<string, unknown>[];
	senden: (nachricht: unknown) => void;
	url: () => string;
}

async function oeffnen(
	page: Page,
	opts: { belegt?: string[]; positionen?: ReturnType<typeof position>[] } = {},
): Promise<Gegenstelle> {
	const gesendet: Record<string, unknown>[] = [];
	let verbindung: WebSocketRoute | null = null;
	await page.routeWebSocket(/\/api\/ws\/track\//, (ws) => {
		verbindung = ws;
		ws.onMessage((roh) => gesendet.push(JSON.parse(String(roh))));
		// Wie der Server: nach dem Aufbau den Stand der anderen Geräte.
		ws.send(JSON.stringify({ type: 'belegungen', vehicle_ids: opts.belegt ?? [] }));
	});
	await blockExternal(page);
	await mockTrack(page, { scope: 'driver', fahrzeuge: [KDOW, ELW], positionen: opts.positionen });
	await page.goto(`/track/${SLUG}`, { waitUntil: 'domcontentloaded' });
	await expect.poll(() => verbindung !== null).toBe(true);
	return {
		gesendet: () => gesendet,
		senden: (n) => verbindung!.send(JSON.stringify(n)),
		url: () => verbindung!.url(),
	};
}

const waehler = (page: Page) => page.getByLabel('Fahrzeug');
const option = (page: Page, id: string) => waehler(page).locator(`option[value="${id}"]`);

test.describe('Fahrzeugbelegung am Fahrer-Link', () => {
	test('ein Fahrzeug, das ein anderes Gerät sendet, lässt sich nicht wählen', async ({ page }) => {
		await oeffnen(page, { belegt: ['v1'] });

		await expect(option(page, 'v1')).toBeDisabled();
		await expect(option(page, 'v1')).toContainText('belegt');
		await expect(option(page, 'v2')).toBeEnabled();
	});

	test('die Wahl belegt das Fahrzeug, das Abwählen gibt es frei', async ({ page }) => {
		const gegen = await oeffnen(page);
		// Das Gerät weist sich aus — sonst behandelt der Server es als alten Client.
		expect(new URL(gegen.url()).searchParams.get('client')).toMatch(/^[A-Za-z0-9_-]{8,64}$/);

		await waehler(page).selectOption('v1');
		await expect
			.poll(() => gegen.gesendet())
			.toContainEqual({ type: 'belegen', vehicle_id: 'v1' });

		await waehler(page).selectOption('v2');
		await expect
			.poll(() => gegen.gesendet())
			.toContainEqual({ type: 'freigeben', vehicle_id: 'v1' });
		expect(gegen.gesendet()).toContainEqual({ type: 'belegen', vehicle_id: 'v2' });
	});

	test('war ein anderes Gerät schneller, ist die Wahl zurückgenommen und gesagt, warum', async ({ page }) => {
		const gegen = await oeffnen(page);
		await waehler(page).selectOption('v1');
		await expect.poll(() => gegen.gesendet()).toContainEqual({ type: 'belegen', vehicle_id: 'v1' });

		gegen.senden({ type: 'belegung_abgelehnt', vehicle_id: 'v1' });

		await expect(waehler(page)).toHaveValue('');
		await expect(page.getByText(/sendet bereits von einem anderen Gerät/)).toBeVisible();
		await expect(option(page, 'v1')).toBeDisabled();
	});

	test('wählt ein anderes Gerät während die Seite offen ist, wird das Fahrzeug gesperrt — und wieder frei', async ({ page }) => {
		const gegen = await oeffnen(page);
		await expect(option(page, 'v2')).toBeEnabled();

		gegen.senden({ type: 'belegung', vehicle_id: 'v2', belegt: true });
		await expect(option(page, 'v2')).toBeDisabled();

		gegen.senden({ type: 'belegung', vehicle_id: 'v2', belegt: false });
		await expect(option(page, 'v2')).toBeEnabled();
	});

	test('eine alte Position allein sperrt kein Fahrzeug', async ({ page }) => {
		// Früher galt „hat eine Position = vergeben", und die bleibt liegen, wenn
		// niemand mehr sendet — das Fahrzeug war dann für immer ausgegraut.
		await oeffnen(page, { positionen: [position('v1')] });

		await expect(option(page, 'v1')).toBeEnabled();
	});
});
