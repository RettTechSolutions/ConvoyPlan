import { test, expect, type Page } from '@playwright/test';
import { blockExternal, convoyPayload, mockOrgPortal } from './fixtures';

// Konvoi aktiv schalten in der Tracking-Ansicht. Zusagen:
//
// - Der Knopf schickt genau `{ status: 'active' }` — kein „aktiv" oder ein
//   anderer Freitext, bei dem Tracker still weiter schweigen.
// - Abschließen fragt nach, weil die Tracker danach verstummen.
// - Wer nicht planen darf, sieht den Status, aber keinen Knopf.

const SLUG = 'ks-org';
const CONVOY = 'c-ks';

async function oeffnen(page: Page, rolle: 'planer' | 'beobachter', status = 'planning') {
	await blockExternal(page);
	await page.routeWebSocket(/\/api\/ws\//, () => {});
	await mockOrgPortal(page, { slug: SLUG, convoyId: CONVOY, rolle });
	const gesendet: unknown[] = [];
	let aktuell = status;
	// Später registriert, also vor mockOrgPortal an der Reihe.
	await page.route(`**/api/convoys/${CONVOY}`, (route) => {
		const req = route.request();
		if (req.method() === 'PUT') {
			const body = JSON.parse(req.postData() ?? '{}');
			gesendet.push(body);
			aktuell = body.status ?? aktuell;
		}
		route.fulfill({ json: { ...convoyPayload(CONVOY), status: aktuell } });
	});
	await page.goto(`/o/${SLUG}/tracking/${CONVOY}`, { waitUntil: 'domcontentloaded' });
	return gesendet;
}

test('Planer schaltet den Konvoi aktiv und schließt ihn ab', async ({ page }) => {
	const gesendet = await oeffnen(page, 'planer');
	const block = page.getByTestId('konvoi-status');
	await expect(block).toContainText('In Planung');

	await block.getByRole('button', { name: /Konvoi aktivieren/ }).click();
	await expect(block).toContainText('Aktiv');
	expect(gesendet).toEqual([{ status: 'active' }]);

	// Abbrechen im Dialog ändert nichts.
	page.once('dialog', (d) => d.dismiss());
	await block.getByRole('button', { name: /abschließen/ }).click();
	await expect(block).toContainText('Aktiv');
	expect(gesendet).toHaveLength(1);

	page.once('dialog', (d) => d.accept());
	await block.getByRole('button', { name: /abschließen/ }).click();
	await expect(block).toContainText('Abgeschlossen');
	expect(gesendet).toEqual([{ status: 'active' }, { status: 'completed' }]);
	await expect(block.getByRole('button', { name: /wieder aktivieren/ })).toBeVisible();
});

test('Beobachter sieht den Status, aber keinen Knopf', async ({ page }) => {
	await oeffnen(page, 'beobachter', 'active');
	const block = page.getByTestId('konvoi-status');
	await expect(block).toContainText('Aktiv');
	await expect(block.getByRole('button')).toHaveCount(0);
});
