import { test, expect, type Page, type WebSocketRoute } from '@playwright/test';
import { blockExternal, fahrzeug, konvoiFahrzeug, mockOrgPortal, mockTrack } from './fixtures';

// Die Führung quittiert einen Alarm am Server — und die Besatzung, die ihn
// ausgelöst hat, sieht es. Vorher quittierte jeder Browser für sich, und das
// liegengebliebene Fahrzeug erfuhr nie, ob jemand den Ausfall gesehen hatte.
// Der Server ist gestellt: er hört mit und antwortet, was er antworten würde.

const ALARM_TS = '2026-09-23T09:12:44.123456+00:00';

interface Gegenstelle {
	gesendet: () => Record<string, unknown>[];
	senden: (nachricht: unknown) => void;
}

async function kanal(page: Page, pfad: RegExp): Promise<() => Gegenstelle> {
	const gesendet: Record<string, unknown>[] = [];
	let verbindung: WebSocketRoute | null = null;
	await page.routeWebSocket(pfad, (ws) => {
		verbindung = ws;
		ws.onMessage((roh) => gesendet.push(JSON.parse(String(roh))));
		ws.send(JSON.stringify({ type: 'belegungen', vehicle_ids: [] }));
	});
	return () => {
		if (!verbindung) throw new Error('Kein Kanal');
		return { gesendet: () => gesendet, senden: (n) => verbindung!.send(JSON.stringify(n)) };
	};
}

test.describe('Alarmquittung am Fahrer-Link (Besatzung)', () => {
	const LF = fahrzeug({ id: 'v1', name: 'LF 10', callsign: 'Florian 1/44', vehicle_status: 'breakdown' });
	const ELW = fahrzeug({ id: 'v2', name: 'ELW 1', callsign: 'Florian 1/11', position: 2 });

	async function oeffnen(page: Page, lf = LF) {
		const gegen = await kanal(page, /\/api\/ws\/track\//);
		await blockExternal(page);
		await mockTrack(page, { scope: 'driver', fahrzeuge: [lf, ELW] });
		await page.goto('/track/qUiTtUnG', { waitUntil: 'domcontentloaded' });
		await page.getByLabel('Fahrzeug').selectOption('v1');
		await expect.poll(() => gegen().gesendet()).toContainEqual({ type: 'belegen', vehicle_id: 'v1' });
		return gegen();
	}

	test('die Besatzung sieht, dass die Führung quittiert hat', async ({ page }) => {
		const gegen = await oeffnen(page);
		const hinweis = page.getByTestId('alarm-quittung');
		await expect(hinweis).toHaveText('Noch nicht von der Führung quittiert.');

		gegen.senden({
			type: 'alarm_quittiert', vehicle_id: 'v1', alarm_ts: ALARM_TS,
			quittiert_von: 'Florian 1/11', quittiert_at: '2026-09-23T09:13:10+00:00',
		});

		await expect(hinweis).toContainText('Von der Führung quittiert: Florian 1/11');
	});

	test('eine Quittung von vor dem Öffnen steht gleich da', async ({ page }) => {
		await oeffnen(page, {
			...LF, alarm_ts: ALARM_TS,
			alarm_quittiert_at: '2026-09-23T09:13:10+00:00', alarm_quittiert_von: 'Anna Zugführer',
		});

		await expect(page.getByTestId('alarm-quittung')).toContainText('quittiert: Anna Zugführer');
	});

	test('eine Quittung für ein anderes Fahrzeug betrifft mich nicht', async ({ page }) => {
		const gegen = await oeffnen(page);
		gegen.senden({
			type: 'alarm_quittiert', vehicle_id: 'v2', alarm_ts: ALARM_TS,
			quittiert_von: 'Florian 1/11', quittiert_at: '2026-09-23T09:13:10+00:00',
		});

		await expect(page.getByTestId('alarm-quittung')).toHaveText('Noch nicht von der Führung quittiert.');
	});
});

test.describe('Alarmquittung in der Tracking-Ansicht (Führung)', () => {
	const SLUG_ORG = 'thw-musterstadt';
	const CONVOY = '22222222-2222-2222-2222-222222222222';

	/** Der Knopf in der Meldungsliste — das Banner oben hat einen eigenen. */
	const quittierKnopf = (page: Page) =>
		page.locator('.alert-row').getByRole('button', { name: 'Quittieren', exact: true });

	async function oeffnen(page: Page) {
		const gegen = await kanal(page, /\/api\/ws\/tracking\//);
		await blockExternal(page);
		await mockOrgPortal(page, {
			slug: SLUG_ORG, convoyId: CONVOY,
			fahrzeuge: [
				konvoiFahrzeug({ position: 1, vehicle: { id: 'v1', name: 'LF 10', callsign: 'Florian 1/44' } }),
				konvoiFahrzeug({ position: 2, vehicle: { id: 'v2', name: 'ELW 1', callsign: 'Florian 1/11' } }),
			],
		});
		await page.goto(`/o/${SLUG_ORG}/tracking/${CONVOY}`, { waitUntil: 'domcontentloaded' });
		await expect.poll(() => { try { gegen(); return true; } catch { return false; } }).toBe(true);
		gegen().senden({
			type: 'alert', alert_type: 'breakdown', vehicle_id: 'v1', vehicle_label: 'Florian 1/44',
			level: 'total', note: 'Kupplung', ts: ALARM_TS,
		});
		await page.getByRole('button', { name: /^Status/ }).click();
		return gegen();
	}

	test('Quittieren geht an den Server, mit Fahrzeug und Alarmzeitpunkt', async ({ page }) => {
		const gegen = await oeffnen(page);

		await quittierKnopf(page).click();

		await expect
			.poll(() => gegen.gesendet())
			.toContainEqual({ type: 'alarm_quittieren', vehicle_id: 'v1', alarm_ts: ALARM_TS });
	});

	test('quittiert ein anderes Führungsgerät, steht es hier mit Namen', async ({ page }) => {
		const gegen = await oeffnen(page);

		gegen.senden({
			type: 'alarm_quittiert', vehicle_id: 'v1',
			// Anders geschrieben, derselbe Zeitpunkt — gemeint ist der Alarm.
			alarm_ts: '2026-09-23T11:12:44.123456+02:00',
			quittiert_von: 'Florian 1/11', quittiert_at: '2026-09-23T09:13:10+00:00',
		});

		await expect(page.getByText('Quittiert von Florian 1/11')).toBeVisible();
		await expect(quittierKnopf(page)).toHaveCount(0);
		// Und die Nachricht wird nicht als Position gelesen.
		await expect(page.getByText('Keine aktiven Meldungen.')).toHaveCount(0);
	});
});
