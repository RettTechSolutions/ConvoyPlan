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
