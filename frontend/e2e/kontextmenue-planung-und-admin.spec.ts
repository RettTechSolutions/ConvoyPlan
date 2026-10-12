import { test, expect } from '@playwright/test';
import {
	CONVOY, ELW, KONVOI, MTW, ORG, adminBereich, eintrag, menue, orgAdmin, planung, tab, type Aufruf,
} from './kontextmenue-attrappe';

// Kontextmenü in Planung, Org-Admin und Admin-Bereich — in der echten App,
// mit abgefangener API. Die Zusage, die man einem Bildschirmfoto nicht
// ansieht: **jeder Eintrag schickt denselben Aufruf wie der Knopf daneben.**
// Deshalb prüfen die Tests nicht nur, dass ein Eintrag dasteht, sondern was
// beim Server ankommt — Pfad, Methode und Körper.
//
// Die Mechanik selbst (Tastatur, Browsermenü in Feldern, Rand, langes Drücken)
// steht in `kontextmenue.spec.ts`.

// ── Planung ────────────────────────────────────────────────────────────

test('Planung · Karte: „Start hier setzen" schickt den Punkt unter dem Zeiger', async ({ page }) => {
	const aufrufe = await planung(page);
	const karte = page.locator('.map-area .maplibregl-canvas');
	const box = (await karte.boundingBox())!;
	// Links unten auf der Karte: weg von Markern, Zoomknöpfen und Hinweisleisten.
	await karte.click({ button: 'right', position: { x: box.width * 0.25, y: box.height * 0.8 } });

	await expect(menue(page)).toBeVisible();
	// Titel: die Koordinaten des Punkts.
	await expect(menue(page).locator('.titel').first()).toHaveText(/^\d+\.\d{5}, \d+\.\d{5}$/);
	await expect(eintrag(page, 'Route berechnen')).toBeEnabled();
	await expect(menue(page).getByRole('menuitemcheckbox', { name: 'Sperrungen anzeigen' })).toHaveAttribute('aria-checked', 'false');
	await expect(eintrag(page, 'Koordinaten kopieren')).toBeVisible();

	await eintrag(page, 'Start hier setzen').click();
	await expect.poll(() => aufrufe.find((a) => a.methode === 'PUT')).toBeTruthy();
	const put = aufrufe.find((a) => a.methode === 'PUT')!;
	expect(put.pfad).toBe(`/api/convoys/${CONVOY}`);
	const start = (put.koerper as { start_point: { lat: number; lon: number } }).start_point;
	// Irgendwo im sichtbaren Ausschnitt um Deutschland — nicht 0/0, nicht der alte Start.
	expect(start.lat).toBeGreaterThan(40);
	expect(start.lat).toBeLessThan(60);
	expect(start).not.toEqual(KONVOI.start_point);
	expect(Object.keys(put.koerper as object)).toEqual(['start_point']);
});

test('Planung · Karte: Rechtsklick auf einen Wegpunkt-Marker zeigt dessen Menü', async ({ page }) => {
	await planung(page);
	await page.locator('.maplibregl-marker', { hasText: 'WP Erfurt' }).click({ button: 'right', position: { x: 6, y: 6 } });
	await expect(menue(page).locator('.titel').first()).toHaveText('WP Erfurt');
	await expect(eintrag(page, 'Bearbeiten')).toBeVisible();
	await expect(eintrag(page, 'Löschen')).toBeVisible();
	// Kein Kartenmenü darunter oder daneben.
	await expect(eintrag(page, 'Start hier setzen')).toHaveCount(0);
	await expect(menue(page)).toHaveCount(1);
});

test('Planung · Wegpunkte: Umsortieren und Löschen gehen denselben Weg wie Ziehen und ✕', async ({ page }) => {
	const aufrufe = await planung(page);
	await tab(page, 'Wegpunkte').click();
	const zeile = (name: string) => page.locator('.wp-item', { hasText: name });

	// Der erste Punkt kann nicht weiter nach oben.
	await zeile('WP Fulda').click({ button: 'right', position: { x: 8, y: 8 } });
	await expect(eintrag(page, 'Nach oben')).toBeDisabled();
	await page.keyboard.press('Escape');

	await zeile('WP Jena').click({ button: 'right', position: { x: 8, y: 8 } });
	await eintrag(page, 'An den Anfang').click();
	await expect.poll(() => aufrufe.filter((a) => a.methode === 'PATCH').length).toBe(1);
	expect(aufrufe[0]).toEqual({
		methode: 'PATCH',
		pfad: `/api/convoys/${CONVOY}/waypoints/reorder`,
		koerper: [
			{ id: 'wp-jena', order_index: 0 },
			{ id: 'wp-fulda', order_index: 1 },
			{ id: 'wp-erfurt', order_index: 2 },
		],
	});
	await expect(page.locator('.wp-item').first()).toContainText('WP Jena');

	await zeile('WP Erfurt').click({ button: 'right', position: { x: 8, y: 8 } });
	await eintrag(page, 'Löschen').click();
	await expect.poll(() => aufrufe.some((a) => a.methode === 'DELETE')).toBe(true);
	expect(aufrufe.find((a) => a.methode === 'DELETE')!.pfad).toBe(`/api/convoys/${CONVOY}/waypoints/wp-erfurt`);
});

test('Planung · Marschfolge: „An die Spitze" speichert die neue Reihenfolge', async ({ page }) => {
	const aufrufe = await planung(page);
	await tab(page, 'Fahrzeuge').click();
	const reihe = page.locator('.convoy-vehicle-row', { hasText: 'ELW 1' });
	await reihe.click({ button: 'right', position: { x: 8, y: 8 } });
	await expect(menue(page).locator('.titel').first()).toHaveText('3. ELW 1');
	// Ohne Funkrufnamen gibt es nichts zu kopieren.
	await expect(eintrag(page, 'Funkrufname kopieren')).toHaveCount(0);
	await eintrag(page, 'An die Spitze').click();

	await expect.poll(() => aufrufe.find((a) => a.pfad.endsWith('/vehicles/reorder'))).toBeTruthy();
	expect(aufrufe.find((a) => a.pfad.endsWith('/vehicles/reorder'))!.koerper).toEqual([
		{ vehicle_id: 'v-elw', position: 0 },
		{ vehicle_id: 'v-hlf', position: 1 },
		{ vehicle_id: 'v-mtw', position: 2 },
	]);
	await expect(page.locator('.convoy-vehicle-row').first()).toContainText('ELW 1');
});

test('Planung · Fahrzeugpool: ein Fahrzeug im Verband lässt sich herausnehmen, nicht noch einmal hinzufügen', async ({ page }) => {
	const aufrufe = await planung(page);
	await tab(page, 'Fahrzeuge').click();
	await page.locator('.vehicle-item:not(.convoy-vehicle-row)', { hasText: 'MTW' }).first()
		.click({ button: 'right', position: { x: 8, y: 8 } });
	await expect(menue(page).locator('.titel').first()).toHaveText('MTW · Florian 1/19');
	await expect(menue(page).getByRole('menuitem', { name: /hinzufügen/ })).toHaveCount(0);
	await eintrag(page, 'Aus dem Verband nehmen').click();
	await expect.poll(() => aufrufe.find((a) => a.methode === 'DELETE')?.pfad).toBe(`/api/convoys/${CONVOY}/vehicles/v-mtw`);
});

// ── Org-Admin ──────────────────────────────────────────────────────────

test('Org-Admin · Mitglieder: die Rolle steht im Menü und wechselt wie im Auswahlfeld', async ({ page }) => {
	const aufrufe = await orgAdmin(page);
	await page.getByRole('row', { name: /anna@example.org/ }).getByRole('cell', { name: 'anna@example.org' })
		.click({ button: 'right' });
	await expect(menue(page).locator('.titel').first()).toHaveText('Anna Lutz');
	const rolle = (name: string) => menue(page).getByRole('menuitemradio', { name: `Rolle: ${name}` });
	await expect(rolle('Beobachter')).toHaveAttribute('aria-checked', 'true');
	await expect(rolle('Planer')).toHaveAttribute('aria-checked', 'false');

	await rolle('Planer').click();
	await expect.poll(() => aufrufe[0]).toEqual({
		methode: 'PATCH', pfad: `/api/organizations/${ORG}/members/u-anna`, koerper: { role: 'planer' },
	});
});

test('Org-Admin · Mitglieder: dieselbe Rolle noch einmal schickt nichts, Entfernen fragt nach', async ({ page }) => {
	const aufrufe = await orgAdmin(page);
	const ben = page.getByRole('cell', { name: 'ben@example.org' });
	// Ohne Namen steht die E-Mail im Titel.
	await ben.click({ button: 'right' });
	await expect(menue(page).locator('.titel').first()).toHaveText('ben@example.org');
	await menue(page).getByRole('menuitemradio', { name: 'Rolle: Planer' }).click();
	await expect(menue(page)).toHaveCount(0);

	// Wie der ✕-Knopf: erst die Rückfrage. Abgelehnt → kein Aufruf.
	await ben.click({ button: 'right' });
	page.once('dialog', (d) => d.dismiss());
	await eintrag(page, 'Aus der Organisation entfernen').click();
	await ben.click({ button: 'right' });
	page.once('dialog', (d) => d.accept());
	await eintrag(page, 'Aus der Organisation entfernen').click();
	await expect.poll(() => aufrufe).toEqual([
		{ methode: 'DELETE', pfad: `/api/organizations/${ORG}/members/u-ben`, koerper: null },
	]);
});

// ── Admin-Bereich ──────────────────────────────────────────────────────

test('Admin · Benutzer: Schalter zeigen den Stand, ein Klick schaltet um wie der Knopf', async ({ page }) => {
	const aufrufe = await adminBereich(page);
	await page.getByRole('cell', { name: 'carl@example.org' }).click({ button: 'right' });
	await expect(menue(page).locator('.titel').first()).toHaveText('Carl Meier');
	await expect(menue(page).getByRole('menuitemcheckbox', { name: 'Aktiv' })).toHaveAttribute('aria-checked', 'false');
	await expect(menue(page).getByRole('menuitemcheckbox', { name: 'Superadmin' })).toHaveAttribute('aria-checked', 'false');
	// MFA zurücksetzen nur, wo MFA an ist — hier ja.
	await expect(eintrag(page, 'MFA zurücksetzen')).toBeVisible();
	// Ohne SMTP kein Versand per Mail — gesperrt mit Grund, wie der Knopf.
	await expect(eintrag(page, 'Neues Passwort per E-Mail')).toBeDisabled();
	await expect(eintrag(page, 'Neues Passwort per E-Mail')).toHaveAttribute('title', /SMTP/);

	await menue(page).getByRole('menuitemcheckbox', { name: 'Aktiv' }).click();
	await expect.poll(() => aufrufe[0]).toEqual({
		methode: 'PATCH', pfad: '/api/admin/users/u-carl', koerper: { is_active: true },
	});

	// Anna hat kein MFA: kein Eintrag dafür.
	await page.getByRole('cell', { name: 'anna@example.org' }).click({ button: 'right' });
	await expect(eintrag(page, 'MFA zurücksetzen')).toHaveCount(0);
});

test('Admin · Organisationen: Code und Anmeldelink kopieren', async ({ page, context }) => {
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);
	await adminBereich(page);
	await page.locator('.tab', { hasText: 'Organisationen' }).click();
	const zeile = page.getByRole('cell', { name: 'THW OV Musterstadt' });
	await zeile.click({ button: 'right' });
	await expect(menue(page).locator('.titel').first()).toHaveText('THW OV Musterstadt');
	await eintrag(page, 'Code kopieren').click();
	await expect(page.getByRole('status')).toHaveText('In die Zwischenablage kopiert');
	expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('thw-musterstadt');

	await zeile.click({ button: 'right' });
	await eintrag(page, 'Anmeldelink kopieren').click();
	await expect.poll(() => page.evaluate(() => navigator.clipboard.readText()))
		.toBe('http://localhost:4173/o/thw-musterstadt/login');
});

test('Admin · Benutzer: mit der Maus geöffnet ist kein Eintrag vorgewählt, die Pfeiltasten gehen trotzdem', async ({ page }) => {
	await adminBereich(page);
	// Eine Tabellenzelle ist nicht fokussierbar — genau dann zeichnete Chrome
	// den Fokus auf dem ersten Eintrag sichtbar, und er sah aus wie gewählt.
	await page.getByRole('cell', { name: 'anna@example.org' }).click({ button: 'right' });
	await expect(menue(page)).toBeFocused();
	await expect(menue(page).locator(':focus-visible')).toHaveCount(0);

	await page.keyboard.press('ArrowDown');
	await expect(eintrag(page, 'Bearbeiten…')).toBeFocused();
	await page.keyboard.press('ArrowUp');
	await expect(eintrag(page, 'Löschen')).toBeFocused();
});
