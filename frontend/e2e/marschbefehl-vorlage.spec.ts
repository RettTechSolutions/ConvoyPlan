import { test, expect, type Route } from '@playwright/test';
import { GRUNDLAGE, MITGLIEDER, ORG, SLUG, mockApi, tab } from './kontextmenue-attrappe';

// Word-Vorlage für den Marschbefehl im Org-Admin
// (backend/app/services/marschbefehl_vorlage.py).
//
// Die Zusagen, die man einem Bildschirmfoto nicht ansieht:
// - Die Beispielvorlage kommt als .docx aus dem Backend, nicht aus einer
//   Datei im Frontend — sonst liefe ihre Feldübersicht dem Export davon.
// - Eine abgewiesene Vorlage zeigt die Meldung des Backends wörtlich: Sie nennt
//   das falsch geschriebene Feld, und genau das braucht, wer in Word korrigiert.
//   Der Stand bleibt „keine eigene Vorlage".
// - Die Datei geht als Multipart an genau einen Endpunkt, mit Namen.

const LEER = { eigene: false, dateiname: null, groesse: null, hochgeladen_at: null };
const FELDER = {
	gruppen: [{ name: 'konvoi', titel: 'Konvoi und Marschbefehl', felder: [{ name: 'name', beschreibung: 'Name des Konvois' }] }],
	listen: [{ name: 'fahrzeuge', titel: 'Marschfolge', felder: [{ name: 'funkrufname', beschreibung: 'Funkrufname' }] }],
};
const DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

test('Vorlage: Beispiel holen, Fehler sehen, eigene hochladen', async ({ page }) => {
	await mockApi(page, {
		...GRUNDLAGE,
		[`GET /api/organizations/${ORG}/members`]: MITGLIEDER,
		'GET /api/org/marschbefehl-vorlage': LEER,
		'GET /api/org/marschbefehl-vorlage/felder': FELDER,
	});
	await page.route('**/api/org/marschbefehl-vorlage/beispiel', (route) =>
		route.fulfill({ body: 'PK\u0003\u0004', contentType: DOCX }),
	);
	const hochgeladen: { name: string; koerper: string }[] = [];
	let annehmen = false;
	await page.route('**/api/org/marschbefehl-vorlage', (route: Route) => {
		const req = route.request();
		if (req.method() !== 'POST') return route.fallback();
		const koerper = req.postDataBuffer()?.toString('latin1') ?? '';
		const name = /filename="([^"]+)"/.exec(koerper)?.[1] ?? '';
		hochgeladen.push({ name, koerper });
		if (!annehmen) {
			return route.fulfill({
				status: 400,
				json: { detail: 'Unbekanntes Feld „nmae“. Die verfügbaren Felder stehen in der Beispielvorlage.' },
			});
		}
		return route.fulfill({
			json: { eigene: true, dateiname: name, groesse: 4, hochgeladen_at: '2026-10-19T08:00:00Z' },
		});
	});

	await page.goto(`/o/${SLUG}/admin`, { waitUntil: 'domcontentloaded' });
	await tab(page, 'Marschbefehl').click();
	const stand = page.getByTestId('vorlage-stand');
	await expect(stand).toContainText('Keine eigene Vorlage');

	const download = page.waitForEvent('download');
	await page.getByRole('button', { name: /Beispielvorlage herunterladen/ }).click();
	expect((await download).suggestedFilename()).toBe('Marschbefehl-Vorlage.docx');

	const datei = page.getByTestId('vorlage-datei');
	await datei.setInputFiles({ name: 'Unser Befehl.docx', mimeType: DOCX, buffer: Buffer.from('PK\u0003\u0004') });
	await expect(page.getByRole('alert')).toHaveText(/Unbekanntes Feld „nmae“/);
	await expect(stand).toContainText('Keine eigene Vorlage');

	annehmen = true;
	await datei.setInputFiles({ name: 'Unser Befehl.docx', mimeType: DOCX, buffer: Buffer.from('PK\u0003\u0004') });
	await expect(stand).toContainText('Eigene Vorlage: Unser Befehl.docx');
	await expect(page.getByRole('button', { name: 'Eigene Vorlage entfernen' })).toBeVisible();

	expect(hochgeladen).toHaveLength(2);
	expect(hochgeladen[1].name).toBe('Unser Befehl.docx');
	expect(hochgeladen[1].koerper).toContain('name="file"');
});

test('Vorlage: die Feldübersicht zeigt Platzhalter, wie sie in Word stehen', async ({ page }) => {
	await mockApi(page, {
		...GRUNDLAGE,
		[`GET /api/organizations/${ORG}/members`]: MITGLIEDER,
		'GET /api/org/marschbefehl-vorlage': LEER,
		'GET /api/org/marschbefehl-vorlage/felder': FELDER,
	});
	await page.goto(`/o/${SLUG}/admin`, { waitUntil: 'domcontentloaded' });
	await tab(page, 'Marschbefehl').click();
	await page.getByText('Verfügbare Platzhalter').click();
	await expect(page.getByRole('cell', { name: '{{ konvoi.name }}' })).toBeVisible();
	// Listen nutzen den Anfangsbuchstaben als Variable — wie in der Beispielvorlage.
	await expect(page.getByRole('cell', { name: '{{ f.funkrufname }}' })).toBeVisible();
});
