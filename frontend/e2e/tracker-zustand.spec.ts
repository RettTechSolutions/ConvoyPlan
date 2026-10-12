import { test, expect, type Page } from '@playwright/test';
import { blockExternal, konvoiFahrzeug, mockOrgPortal } from './fixtures';

// Akku und Empfang der Tracker am Fahrzeug in der Konvoi-Ansicht. Zusagen,
// die man einem Bildschirmfoto nicht ansieht:
//
// - Die Führung sieht einen schwachen Akku am Fahrzeug, mit Zahl — nicht erst
//   der Org-Admin in seiner Liste.
// - Ein Tracker, der sich seit Minuten nicht gemeldet hat, zeigt keine vollen
//   Balken mehr: alter Empfang ist kein Empfang.
// - Ein Fahrzeug ohne Tracker bekommt keine Symbole.
// - Balken nur über Mobilfunk; über WLAN oder die Begleit-App (BLE) das Symbol des Wegs.

const SLUG = 'tz-org';
const CONVOY = 'c-tz';
const vor = (min: number) => new Date(Date.now() - min * 60_000).toISOString();

async function oeffnen(page: Page, tracker: object[]) {
	await blockExternal(page);
	await page.routeWebSocket(/\/api\/ws\//, () => {});
	await mockOrgPortal(page, {
		slug: SLUG, convoyId: CONVOY, rolle: 'planer',
		fahrzeuge: [
			konvoiFahrzeug({ position: 1, vehicle: { id: 'v-hlf', name: 'HLF 20' } }),
			konvoiFahrzeug({ position: 2, vehicle: { id: 'v-mtw', name: 'MTW' } }),
			konvoiFahrzeug({ position: 3, vehicle: { id: 'v-elw', name: 'ELW' } }),
		],
		tracker,
	});
	const geladen = page.waitForResponse(`**/api/convoys/${CONVOY}/tracker`);
	await page.goto(`/o/${SLUG}/tracking/${CONVOY}`, { waitUntil: 'domcontentloaded' });
	await geladen;
}

test('schwacher Akku und Empfang stehen am Fahrzeug', async ({ page }) => {
	await oeffnen(page, [
		{ vehicle_id: 'v-hlf', zuletzt_gesehen: vor(0), akku_prozent: 12, extern: false,
		  akku_seit: vor(3 * 24 * 60), akku_niedrig: true, signal_dbm: -112 },
		{ vehicle_id: 'v-mtw', zuletzt_gesehen: vor(0), akku_prozent: 64, extern: true,
		  akku_seit: null, akku_niedrig: false, signal_dbm: -85 },
	]);

	const hlf = page.getByTestId('tracker-v-hlf');
	const akku = hlf.getByRole('img', { name: /^Akku 12 %/ });
	await expect(akku).toBeVisible();
	await expect(akku).toHaveAttribute('aria-label', /auf Akku seit 3 Tagen · schwach/);
	await expect(hlf).toContainText('12 %');
	await expect(hlf.getByRole('img', { name: /Empfang/ })).toHaveAttribute('data-balken', '1');

	// Am Bordnetz: volle Balken, Akku ohne Zahl, kein Warnton.
	const mtw = page.getByTestId('tracker-v-mtw');
	await expect(mtw.getByRole('img', { name: /Empfang/ })).toHaveAttribute('data-balken', '4');
	await expect(mtw.getByRole('img', { name: /^Akku 64 % · am Bordnetz/ })).toBeVisible();
	await expect(mtw).not.toContainText('%');

	await expect(page.getByTestId('tracker-v-elw')).toHaveCount(0);
});

test('ein Tracker ohne aktuelle Meldung zeigt keine Balken', async ({ page }) => {
	await oeffnen(page, [
		{ vehicle_id: 'v-hlf', zuletzt_gesehen: vor(25), akku_prozent: 80, extern: false,
		  akku_seit: vor(30), akku_niedrig: false, signal_dbm: -80 },
	]);
	const empfang = page.getByTestId('tracker-v-hlf').getByRole('img', { name: /Keine aktuelle Verbindung/ });
	await expect(empfang).toHaveAttribute('data-balken', '0');
	await expect(empfang).toHaveAttribute('aria-label', /letzter Kontakt vor 25 min/);
});

// Während der Fahrt erwartet die Instanz Bündel. Was davon ausbleibt, steht in
// Worten am Fahrzeug — nicht nur als graue Balken, die man übersieht.
const in_ = (s: number) => new Date(Date.now() + s * 1000).toISOString();

test('ausgebliebene Bündel und gestörtes GPS stehen in Worten am Fahrzeug', async ({ page }) => {
	await oeffnen(page, [
		// Zwei Bündel ausgeblieben: unterbrochen, auch wenn das GPS vorher schon gestört war.
		{ vehicle_id: 'v-hlf', zuletzt_gesehen: vor(2), akku_prozent: 80, extern: true, akku_seit: null,
		  akku_niedrig: false, signal_dbm: -80, unterbrochen_ab: vor(1), gps_gestoert_ab: vor(1) },
		// Bündel kommen, aber keine plausiblen Fixes.
		{ vehicle_id: 'v-mtw', zuletzt_gesehen: vor(0), akku_prozent: 80, extern: true, akku_seit: null,
		  akku_niedrig: false, signal_dbm: -80, unterbrochen_ab: in_(60), gps_gestoert_ab: vor(1) },
		// Alles im Takt.
		{ vehicle_id: 'v-elw', zuletzt_gesehen: vor(0), akku_prozent: 80, extern: true, akku_seit: null,
		  akku_niedrig: false, signal_dbm: -80, unterbrochen_ab: in_(60), gps_gestoert_ab: in_(90) },
	]);

	const hlf = page.getByTestId('tracker-v-hlf');
	await expect(hlf.getByTestId('tracker-stoerung')).toHaveText('Verbindung unterbrochen');
	await expect(hlf.getByRole('img', { name: /^Verbindung unterbrochen · letzter Kontakt vor 2 min/ }))
		.toHaveAttribute('data-balken', '0');

	const mtw = page.getByTestId('tracker-v-mtw');
	await expect(mtw.getByTestId('tracker-stoerung')).toHaveText('GPS gestört');
	// Das Netz steht: die Balken bleiben.
	await expect(mtw.getByRole('img', { name: /Empfang/ })).toHaveAttribute('data-balken', '4');

	await expect(page.getByTestId('tracker-v-elw').getByTestId('tracker-stoerung')).toHaveCount(0);
});

// Über WLAN oder die Begleit-App gibt es kein RSRP: Balken wären dort erfunden. Die
// Ansicht zeigt dann das Symbol des Wegs, mit Worten für Tooltip und Screenreader.
test('über WLAN oder Bluetooth steht das Symbol des Wegs statt Balken', async ({ page }) => {
	await oeffnen(page, [
		{ vehicle_id: 'v-hlf', zuletzt_gesehen: vor(0), akku_prozent: 80, extern: true, akku_seit: null,
		  akku_niedrig: false, signal_dbm: -85, netz: 'wlan' },
		{ vehicle_id: 'v-mtw', zuletzt_gesehen: vor(1), akku_prozent: 80, extern: true, akku_seit: null,
		  akku_niedrig: false, signal_dbm: -85, netz: 'ble' },
		{ vehicle_id: 'v-elw', zuletzt_gesehen: vor(0), akku_prozent: 80, extern: true, akku_seit: null,
		  akku_niedrig: false, signal_dbm: -85, netz: 'mobil' },
	]);

	const wlan = page.getByTestId('tracker-v-hlf').getByRole('img', { name: /^Über WLAN · letzter Kontakt/ });
	await expect(wlan).toHaveAttribute('data-netz', 'wlan');
	await expect(wlan).not.toHaveAttribute('data-balken', /.*/);
	await expect(wlan).toHaveAttribute('title', /^Über WLAN/);

	const ble = page.getByTestId('tracker-v-mtw').getByRole('img', { name: /^Über Bluetooth und die Begleit-App · letzter Kontakt vor 1 min/ });
	await expect(ble).toHaveAttribute('data-netz', 'ble');
	await expect(ble).not.toHaveAttribute('data-balken', /.*/);

	// Über Mobilfunk bleiben die Balken.
	const mobil = page.getByTestId('tracker-v-elw').getByRole('img', { name: /Empfang/ });
	await expect(mobil).toHaveAttribute('data-balken', '4');
	await expect(mobil).toHaveAttribute('data-netz', 'mobil');
});

test('ein verstummter Tracker zeigt auch über WLAN keine aktuelle Verbindung', async ({ page }) => {
	await oeffnen(page, [
		{ vehicle_id: 'v-hlf', zuletzt_gesehen: vor(25), akku_prozent: 80, extern: true, akku_seit: null,
		  akku_niedrig: false, signal_dbm: null, netz: 'wlan' },
	]);
	const empfang = page.getByTestId('tracker-v-hlf').getByRole('img', { name: /^Keine aktuelle Verbindung/ });
	await expect(empfang).toHaveAttribute('data-netz', 'wlan');
	await expect(empfang).toHaveClass(/alt/);
test('„Verbindung unterbrochen" erscheint ohne Neuladen, auch wenn die Abfrage hängt', async ({ page }) => {
	// Gemeldet: der Tracker verstummte, die Ansicht blieb still, erst F5 zeigte
	// die Störung. Die Uhr lief nur nach einer gelungenen Abfrage weiter — und
	// ein `fetch` ohne Frist kann minutenlang hängen.
	await page.clock.install();
	await oeffnen(page, [
		{ vehicle_id: 'v-hlf', zuletzt_gesehen: vor(0), akku_prozent: 80, extern: true, akku_seit: null,
		  akku_niedrig: false, signal_dbm: -80, unterbrochen_ab: in_(20), gps_gestoert_ab: in_(60) },
	]);
	const hlf = page.getByTestId('tracker-v-hlf');
	await expect(hlf).toBeVisible();
	await expect(hlf.getByTestId('tracker-stoerung')).toHaveCount(0);

	// Ab jetzt antwortet die Instanz nicht mehr.
	await page.route(`**/api/convoys/${CONVOY}/tracker`, () => {});
	await page.clock.runFor(40_000);
	await expect(hlf.getByTestId('tracker-stoerung')).toHaveText('Verbindung unterbrochen');
});
