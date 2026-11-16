import { test, expect, type Page } from '@playwright/test';
import { CONVOY, KONVOI, planung, tab, type Aufruf } from './kontextmenue-attrappe';

// Das Formular „Marschbefehl“ in der Planung, in der echten App mit
// abgefangener API. Die Zusagen, die man einem Bildschirmfoto nicht ansieht:
//
// - Es ist gegliedert wie der Ausdruck, also nach FwDV 100, Anlage 4:
//   Kopf, 1.–5., dann Anlagen und Verteiler **ohne** Ziffer, Unterschrift.
// - Jedes Feld landet beim Speichern in seiner Spalte (Migration 0076) —
//   vertauschte Bindungen sähen im Formular richtig aus und druckten falsch.
// - Ein geleertes Feld geht als `null` hinaus. Das Backend löscht es dann;
//   früher blieb der alte Text stehen.
// - Ohne Gefahren-/Schadenlage, erhaltenen Auftrag und Ablaufpunkt wird nicht
//   gespeichert.
//
// Was das PDF daraus macht, prüft `backend/tests/test_marschbefehl_fwdv.py`.

const FWDV_FELDER = [
	'abgangsort', 'marschraum', 'karte', 'lage_eigene', 'kraefte', 'marschfuehrer',
	'einzelgruppen_fuehrer', 'marschabstand', 'beleuchtung', 'marschueberwachung', 'besonderes',
	'verpflegung', 'betriebsstoff', 'instandsetzung', 'aerztliche_versorgung', 'verbindungen',
	'platz_fuehrung', 'verteiler', 'unterschrift_name', 'unterschrift_dienststellung',
] as const;

const modal = (page: Page) => page.locator('.befehl-modal');

/** Ein Feld über seinen zugänglichen Namen; das Pflicht-Sternchen gehört nicht dazu.
 *  Verankert, weil sich Namen überschneiden („Name“, „Ablaufpunkt (Ort)“). */
const feld = (page: Page, beschriftung: string) =>
	modal(page).getByRole('textbox', {
		name: new RegExp(`^${beschriftung.replace(/[/()]/g, '\\$&')}( \\*)?$`),
	});

/** Anlagen und Verteiler haben keine eigene Beschriftung, nur den Abschnittstitel. */
const abschnittsfeld = (page: Page, titel: string) =>
	modal(page)
		.locator('.befehl-section')
		.filter({ has: page.locator('.befehl-section-title', { hasText: new RegExp(`^${titel}$`) }) })
		.locator('textarea');

async function oeffnen(page: Page, konvoi: Record<string, unknown> = {}): Promise<Aufruf[]> {
	const k = { ...KONVOI, ...konvoi };
	const aufrufe = await planung(page, {
		'GET /api/convoys/': [k],
		[`GET /api/convoys/${CONVOY}`]: k,
	});
	await tab(page, 'Export').click();
	await page.getByRole('button', { name: '📋 Marschbefehl' }).click();
	await expect(modal(page)).toBeVisible();
	return aufrufe;
}

const put = (aufrufe: Aufruf[]) => aufrufe.find((a) => a.methode === 'PUT' && a.pfad === `/api/convoys/${CONVOY}`);

test('Das Formular ist gegliedert wie der Marschbefehl nach FwDV 100', async ({ page }) => {
	await oeffnen(page);
	await expect(modal(page).locator('.befehl-section-title')).toHaveText([
		'Kopf', /^1\. Lage/, /^2\. Auftrag/, '3. Durchführung', '4. Versorgung',
		'5. Führung und Verbindung', 'Anlagen', 'Verteiler', 'Unterschrift',
	]);
	await expect(modal(page)).toContainText('FwDV 100, Anlage 4');
	await expect(modal(page)).not.toContainText('6. Anlagen');
});

test('Speichern schickt jedes Feld an seinen FwDV-Punkt', async ({ page }) => {
	const aufrufe = await oeffnen(page);

	const eingaben: [string, string, string][] = [
		// [Beschriftung, Spalte, Wert]
		['Abgangsort', 'abgangsort', 'Musterstadt'],
		['Marsch in den Raum', 'marschraum', 'Grafschaft'],
		['Karte', 'karte', 'TK 1:50 000'],
		['Gefahren- / Schadenlage', 'lage', 'Hochwasser im Ahrtal'],
		['Eigene Lage', 'lage_eigene', 'Zug einsatzbereit'],
		['Zuteilung, Unterstellung und Abgabe von Kräften', 'kraefte', 'Unterstellt EL Ahrweiler'],
		['Erhaltener Auftrag', 'auftrag', 'Verlegung in den BR Grafschaft'],
		['Ablaufpunkt (Ort)', 'ablaufpunkt', 'Feuerwache Musterstadt'],
		['Marschführer/in', 'marschfuehrer', 'BI Muster'],
		['Marschabstand', 'marschabstand', '5 min'],
		['Führer/innen der Einzelgruppen', 'einzelgruppen_fuehrer', 'Gr. 1: HBM A'],
		['Beleuchtung', 'beleuchtung', 'Abblendlicht'],
		['Marschüberwachung und Verkehrssicherung', 'marschueberwachung', 'Lotse AS 12'],
		['Besondere Einzelheiten je nach Lage', 'besonderes', 'Baustelle A 3'],
		['Verpflegung', 'verpflegung', 'EPa'],
		['Betriebsstoff', 'betriebsstoff', 'Tanken in Hösbach'],
		['Instandsetzungsdienst', 'instandsetzung', 'WLF schleppt ab'],
		['Ärztliche Versorgung', 'aerztliche_versorgung', 'RTW am Schluss'],
		['Sonstige Verbindungen, Lotsenstellen und Verkehrsleitpunkte', 'verbindungen', 'Lotsenstelle AS 12'],
		['Platz der Führungskraft', 'platz_fuehrung', 'ELW an der Spitze'],
		['Name', 'unterschrift_name', 'M. Muster'],
		['Dienststellung', 'unterschrift_dienststellung', 'Kreisbrandinspektor'],
	];
	for (const [beschriftung, , wert] of eingaben) await feld(page, beschriftung).fill(wert);
	await abschnittsfeld(page, 'Anlagen').fill('Roadbook');
	await abschnittsfeld(page, 'Verteiler').fill('Alle Fahrzeugführer');

	await modal(page).getByRole('button', { name: 'Speichern & Schließen' }).click();
	await expect(modal(page)).toBeHidden();

	const koerper = put(aufrufe)!.koerper as Record<string, unknown>;
	for (const [beschriftung, spalte, wert] of eingaben) expect(koerper[spalte], beschriftung).toBe(wert);
	expect(koerper.anlagen).toBe('Roadbook');
	expect(koerper.verteiler).toBe('Alle Fahrzeugführer');
	// Jede Spalte der Migration kommt mit, keine fehlt.
	for (const spalte of FWDV_FELDER) expect(koerper, spalte).toHaveProperty(spalte);
});

test('Gespeichertes steht im Formular, und ein geleertes Feld geht als null hinaus', async ({ page }) => {
	const aufrufe = await oeffnen(page, {
		lage: 'Hochwasser', auftrag: 'Verlegung', ablaufpunkt: 'Wache', ablaufzeit: '2026-11-20T06:45:00',
		karte: 'TK 1:50 000', verteiler: 'Alle Fahrzeugführer', unterschrift_name: 'M. Muster',
	});
	await expect(feld(page, 'Karte')).toHaveValue('TK 1:50 000');
	await expect(feld(page, 'Name')).toHaveValue('M. Muster');
	await expect(abschnittsfeld(page, 'Verteiler')).toHaveValue('Alle Fahrzeugführer');

	await abschnittsfeld(page, 'Verteiler').fill('');
	await feld(page, 'Name').fill('   ');
	await modal(page).getByRole('button', { name: 'Speichern & Schließen' }).click();
	await expect(modal(page)).toBeHidden();

	const koerper = put(aufrufe)!.koerper as Record<string, unknown>;
	expect(koerper.verteiler).toBeNull();
	// Nur Leerzeichen zählt als leer.
	expect(koerper.unterschrift_name).toBeNull();
	expect(koerper.karte).toBe('TK 1:50 000');
	// Nie Angefasstes ebenfalls als null — der Server hat dort nichts stehen.
	expect(koerper.verpflegung).toBeNull();
});

test('Ohne Schadenlage, Auftrag und Ablaufpunkt wird nicht gespeichert', async ({ page }) => {
	const aufrufe = await oeffnen(page);
	await modal(page).getByRole('button', { name: 'Speichern & Schließen' }).click();

	const fehler = modal(page).locator('.error-bar');
	await expect(fehler).toContainText('Gefahren- / Schadenlage');
	await expect(fehler).toContainText('Erhaltener Auftrag');
	await expect(fehler).toContainText('Ablaufpunkt');
	await expect(modal(page)).toBeVisible();
	await expect(feld(page, 'Gefahren- / Schadenlage')).toHaveClass(/field-invalid/);
	expect(put(aufrufe)).toBeUndefined();
});

test('„Ergänzend“ erscheint nur, wenn noch eine alte Angabe zur Versorgung da ist', async ({ page }) => {
	await oeffnen(page);
	await expect(modal(page).getByText('Ergänzend (frühere Angabe „Versorgung“)')).toHaveCount(0);
});

test('Eine alte Angabe zur Versorgung bleibt sichtbar und wird mitgespeichert', async ({ page }) => {
	const aufrufe = await oeffnen(page, {
		lage: 'Hochwasser', auftrag: 'Verlegung', ablaufpunkt: 'Wache', ablaufzeit: '2026-11-20T06:45:00',
		versorgung: 'Kraftstoffkarte im ELW',
	});
	await expect(feld(page, 'Ergänzend (frühere Angabe „Versorgung“)')).toHaveValue('Kraftstoffkarte im ELW');
	await modal(page).getByRole('button', { name: 'Speichern & Schließen' }).click();
	await expect(modal(page)).toBeHidden();
	expect((put(aufrufe)!.koerper as Record<string, unknown>).versorgung).toBe('Kraftstoffkarte im ELW');
});

test('„Speichern & PDF“ speichert zuerst und holt danach den Marschbefehl', async ({ page }) => {
	await oeffnen(page, {
		lage: 'Hochwasser', auftrag: 'Verlegung', ablaufpunkt: 'Wache', ablaufzeit: '2026-11-20T06:45:00',
	});
	const reihenfolge: string[] = [];
	page.on('request', (r) => {
		const pfad = new URL(r.url()).pathname;
		if (r.method() === 'PUT' && pfad === `/api/convoys/${CONVOY}`) reihenfolge.push('speichern');
		if (pfad === `/api/convoys/${CONVOY}/export/pdf`) reihenfolge.push('pdf');
	});
	await page.route(`**/api/convoys/${CONVOY}/export/pdf`, (route) =>
		route.fulfill({ body: '%PDF-1.4\n', contentType: 'application/pdf' }),
	);
	const download = page.waitForEvent('download');
	await modal(page).getByRole('button', { name: '🖨 Speichern & PDF' }).click();
	expect((await download).suggestedFilename()).toBe(`${KONVOI.name}.pdf`);
	expect(reihenfolge).toEqual(['speichern', 'pdf']);
});
