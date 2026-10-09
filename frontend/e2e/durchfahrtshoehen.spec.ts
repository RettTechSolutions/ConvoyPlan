import { test, expect, type Page } from '@playwright/test';

// Durchfahrtshöhen in der Planungsansicht. Gesperrt hat das Routing schon
// vorher, still — dieser Block sagt, wie knapp es unter dem Rest hindurchgeht.
// Die Zusagen:
//  - enge und knappe Stellen stehen sofort da, mit Kilometer, Höhe und
//    Spielraum; die freien nur auf Nachfrage;
//  - ohne erfasste Fahrzeughöhe sagt der Block, dass nichts gemieden wurde,
//    statt Stellen als unbedenklich zu zeigen;
//  - eine Route von vor der Auswertung zeigt nichts — „keine Beschränkung"
//    wäre dort eine Behauptung ohne Grundlage;
//  - die Herkunft der Zahlen steht immer dabei;
//  - Brücken über der Route ohne Höhenangabe stehen darunter, die auf Autobahn
//    und Kraftfahrstraße erst auf Nachfrage; ob gesucht wurde, läuft oder
//    scheiterte, ist zu unterscheiden — „nichts gefunden" sagt nur, wer gesucht hat.

const HUELLE = 'http://localhost:4174';
const block = (page: Page) => page.getByRole('region', { name: 'Durchfahrtshöhen' });
const bekannte = (page: Page) =>
	block(page).getByRole('list', { name: 'Bekannte Höhenbeschränkungen' }).getByRole('listitem');
const bruecken = (page: Page) =>
	block(page).getByRole('list', { name: 'Brücken ohne Höhenangabe' }).getByRole('listitem');

async function oeffnen(page: Page, fall: string) {
	await page.goto(`${HUELLE}/?k=hoehen&fall=${fall}`);
	await expect(page.getByText('Route berechnet.')).toBeVisible();
}

test('enge und knappe Stellen stehen da, die freien erst auf Nachfrage', async ({ page }) => {
	await oeffnen(page, 'gemischt');
	const eintraege = bekannte(page);

	await expect(block(page)).toContainText('Höchstes Fahrzeug: 3,65 m');
	await expect(block(page)).toContainText('1 Fahrzeug ohne Höhenangabe, nicht berücksichtigt');
	await expect(eintraege).toHaveCount(2);
	await expect(eintraege.nth(0)).toContainText('km 12,4');
	await expect(eintraege.nth(0)).toContainText('3,7 m');
	await expect(eintraege.nth(0)).toContainText('+5 cm');
	await expect(eintraege.nth(0)).toContainText('eng – vor Ort prüfen');
	await expect(eintraege.nth(1)).toContainText('+25 cm');
	await expect(eintraege.nth(1)).toContainText('knapp');

	await block(page).getByRole('button', { name: '+ 2 weitere mit mindestens 30 cm Spielraum' }).click();
	// In Fahrtrichtung, nicht nach Stufe sortiert.
	await expect(eintraege).toHaveCount(4);
	await expect(eintraege.nth(1)).toContainText('km 30,1');
	await expect(eintraege.nth(1)).toContainText('+85 cm');
});

test('sind alle frei, sagt der Block das in einem Satz', async ({ page }) => {
	await oeffnen(page, 'alle_frei');
	await expect(block(page)).toContainText('1 Höhenbeschränkung, alle mit mindestens 30 cm Spielraum.');
	await expect(bekannte(page)).toHaveCount(0);
});

test('ohne Fahrzeughöhe wird nichts als unbedenklich gezeigt', async ({ page }) => {
	await oeffnen(page, 'ohne_hoehe');
	await expect(block(page)).toContainText('Keine Fahrzeughöhe erfasst – die Route meidet keine Höhenbeschränkung.');
	const [eintrag] = await bekannte(page).all();
	await expect(eintrag).toContainText('3,5 m');
	await expect(eintrag).toContainText('Höhe fehlt');
	await expect(eintrag).not.toContainText('cm');
});

test('ohne Beschränkung auf der Strecke steht das da', async ({ page }) => {
	await oeffnen(page, 'leer');
	await expect(block(page)).toContainText('Keine Höhenbeschränkung auf der Strecke bekannt.');
});

test('die Herkunft der Zahlen steht immer dabei', async ({ page }) => {
	for (const fall of ['gemischt', 'ohne_hoehe', 'leer']) {
		await oeffnen(page, fall);
		await expect(block(page)).toContainText('Aus OpenStreetMap, auf 10 cm gerundet.');
		await expect(block(page)).toContainText('Bei Brücken ohne Angabe ist die Höhe unbekannt.');
		await expect(block(page)).toContainText('Maßgeblich ist die Beschilderung vor Ort.');
	}
});

test('eine Route von vor der Auswertung zeigt keinen Block', async ({ page }) => {
	await oeffnen(page, 'alt');
	await expect(block(page)).toHaveCount(0);
});

test('Brücken ohne Höhenangabe stehen darunter, Schnellstraßen auf Nachfrage', async ({ page }) => {
	await oeffnen(page, 'gemischt');
	await expect(bruecken(page)).toHaveCount(1);
	await expect(bruecken(page).first()).toContainText('km 5,2');
	await expect(bruecken(page).first()).toContainText('Eisenbahnbrücke');
	await expect(bruecken(page).first()).toContainText('Ammertalbahn');
	await expect(bruecken(page).first().getByRole('link', { name: 'OSM' }))
		.toHaveAttribute('href', 'https://www.openstreetmap.org/way/101');

	await block(page).getByRole('button', { name: '+ 2 auf Autobahn- oder Kraftfahrstraßenabschnitten' }).click();
	await expect(bruecken(page)).toHaveCount(3);
	await expect(bruecken(page).nth(2)).toContainText('Fuß-/Radwegbrücke');
});

test('wer gesucht und nichts gefunden hat, sagt das', async ({ page }) => {
	await oeffnen(page, 'leer');
	await expect(block(page)).toContainText('Keine Brücke ohne Höhenangabe über der Route gefunden.');
});

test('ungesucht ist nicht „nichts gefunden" — und lässt sich anstoßen', async ({ page }) => {
	await oeffnen(page, 'ungesucht');
	await expect(block(page)).toContainText('Nicht gesucht.');
	await expect(block(page)).not.toContainText('Keine Brücke');
	await block(page).getByRole('button', { name: 'Jetzt suchen' }).click();
	await expect(page.getByText('Suchen geklickt: 1')).toBeVisible();
	await expect(block(page)).toContainText('Suche läuft …');
});

test('eine gescheiterte Suche sagt das und bietet einen neuen Versuch', async ({ page }) => {
	await oeffnen(page, 'suche_fehler');
	await expect(block(page)).toContainText('Suche fehlgeschlagen');
	await block(page).getByRole('button', { name: 'Erneut suchen' }).click();
	await expect(page.getByText('Suchen geklickt: 1')).toBeVisible();
});

test('wer nicht suchen darf, bekommt keinen Knopf', async ({ page }) => {
	await oeffnen(page, 'ohne_knopf');
	await expect(block(page)).toContainText('Nicht gesucht.');
	await expect(block(page).getByRole('button')).toHaveCount(0);
});
