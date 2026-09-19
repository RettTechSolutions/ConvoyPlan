import { test, expect, type Page } from '@playwright/test';
import { blockExternal, fahrzeug, konvoiFahrzeug, mockOrgPortal, mockTrack, type TrackFahrzeug } from './fixtures';

const SLUG = '6dA4KrUG';

async function oeffnen(page: Page, fahrzeuge: TrackFahrzeug[], scope: 'track' | 'driver' = 'track') {
	await blockExternal(page);
	await mockTrack(page, { scope, fahrzeuge });
	await page.goto(`/track/${SLUG}`, { waitUntil: 'domcontentloaded' });
}

const staerke = (page: Page, id = 'v1') => page.getByTestId(`staerke-${id}`);

test.describe('Mannschaftsstärke in der Fahrzeugliste', () => {
	test('ohne Meldung steht kein Zahlenwert — „unbekannt" ist nicht „unbesetzt"', async ({ page }) => {
		await oeffnen(page, [
			fahrzeug({ staerke_soll_fuehrer: 0, staerke_soll_unterfuehrer: 1, staerke_soll_mannschaften: 8 }),
		]);

		const feld = staerke(page);
		await expect(feld).toBeVisible();
		// Die eigentliche Zusage: nichts, was sich als gemeldete Zahl lesen ließe.
		await expect(feld).not.toContainText('0/0/0');
		await expect(feld).toContainText('–/–/–');
		// Das Soll darf danebenstehen, damit die Führung weiß, was fehlt.
		await expect(feld).toContainText('0/1/8//9');
	});

	test('gemeldete Stärke steht in der Notation F/U/M//Gesamt', async ({ page }) => {
		await oeffnen(page, [
			fahrzeug({ staerke_ist_fuehrer: 0, staerke_ist_unterfuehrer: 1, staerke_ist_mannschaften: 8 }),
		]);

		await expect(staerke(page)).toContainText('0/1/8//9');
	});

	test('eine unbesetzte Meldung bleibt eine Meldung', async ({ page }) => {
		await oeffnen(page, [
			fahrzeug({ staerke_ist_fuehrer: 0, staerke_ist_unterfuehrer: 0, staerke_ist_mannschaften: 0 }),
		]);

		const feld = staerke(page);
		await expect(feld).toContainText('0/0/0//0');
		await expect(feld).not.toContainText('–/–/–');
	});

	test('eine Abweichung vom Soll ist als solche benannt, eine Übereinstimmung nicht', async ({ page }) => {
		await oeffnen(page, [
			fahrzeug({
				id: 'v1', name: 'LF 10',
				staerke_soll_fuehrer: 0, staerke_soll_unterfuehrer: 1, staerke_soll_mannschaften: 8,
				staerke_ist_fuehrer: 0, staerke_ist_unterfuehrer: 1, staerke_ist_mannschaften: 6,
			}),
			fahrzeug({
				id: 'v2', name: 'MTW 2',
				staerke_soll_fuehrer: 0, staerke_soll_unterfuehrer: 1, staerke_soll_mannschaften: 8,
				staerke_ist_fuehrer: 0, staerke_ist_unterfuehrer: 1, staerke_ist_mannschaften: 8,
			}),
		]);

		// Farbe allein trägt die Aussage nicht — sie muss im Text stehen.
		await expect(staerke(page, 'v1')).toHaveAttribute('title', /Abweichung/);
		await expect(staerke(page, 'v1')).toContainText('0/1/8//9');
		await expect(staerke(page, 'v2')).not.toHaveAttribute('title', /Abweichung/);
	});
});

test.describe('Stärke melden (Fahrer-Link)', () => {
	test('die Meldung geht erst auf Knopfdruck — und als Zahlen', async ({ page }) => {
		const gesendet: string[] = [];
		// Der Fahrer-Link spricht über WebSocket; hier hört die Gegenstelle mit,
		// statt ein Backend zu starten.
		await page.routeWebSocket(/\/api\/ws\/track\//, (ws) => {
			ws.onMessage((nachricht) => gesendet.push(String(nachricht)));
		});
		await oeffnen(page, [fahrzeug({ id: 'v1', name: 'LF 10' })], 'driver');

		await page.getByLabel('Fahrzeug').selectOption('v1');
		await page.getByLabel('Führer', { exact: true }).fill('0');
		await page.getByLabel('Unterführer', { exact: true }).fill('1');
		await page.getByLabel('Mannschaften', { exact: true }).fill('8');

		// Zwischenstände bleiben im Fahrzeug: Tippen ist keine Meldung.
		expect(gesendet.filter((f) => f.includes('staerke'))).toHaveLength(0);

		await page.getByRole('button', { name: /Stärke melden/ }).click();

		await expect.poll(() => gesendet.filter((f) => f.includes('staerke')).length).toBe(1);
		const rahmen = JSON.parse(gesendet.find((f) => f.includes('staerke'))!);
		expect(rahmen).toMatchObject({
			type: 'staerke', vehicle_id: 'v1', fuehrer: 0, unterfuehrer: 1, mannschaften: 8,
		});
		// Zahlen, keine Zeichenketten — sonst weist das Backend die Meldung ab.
		expect(typeof rahmen.mannschaften).toBe('number');
	});
});

test.describe('Verbandsstärke in der Tracking-Ansicht', () => {
	const SLUG_ORG = 'thw-musterstadt';
	const CONVOY = '11111111-1111-1111-1111-111111111111';

	test('die Summe zählt nur Gemeldetes und nennt die offenen Fahrzeuge', async ({ page }) => {
		await blockExternal(page);
		await mockOrgPortal(page, {
			slug: SLUG_ORG,
			convoyId: CONVOY,
			fahrzeuge: [
				konvoiFahrzeug({
					position: 1,
					staerke_ist_fuehrer: 0, staerke_ist_unterfuehrer: 1, staerke_ist_mannschaften: 8,
					vehicle: { id: 'v1', name: 'LF 10', callsign: 'Florian 1' },
				}),
				konvoiFahrzeug({ position: 2, vehicle: { id: 'v2', name: 'MTW 2', callsign: 'Florian 2' } }),
			],
		});
		await page.goto(`/o/${SLUG_ORG}/tracking/${CONVOY}`, { waitUntil: 'domcontentloaded' });

		const summe = page.getByTestId('verbandsstaerke');
		// Das schweigende Fahrzeug darf die Summe nicht als 0 mitziehen …
		await expect(summe).toContainText('0/1/8//9');
		// … sondern muss als offene Meldung benannt sein.
		await expect(summe).toContainText('1 ohne Meldung');
	});

	test('ohne eine einzige Meldung steht keine Zahl, sondern der Hinweis', async ({ page }) => {
		await blockExternal(page);
		await mockOrgPortal(page, {
			slug: SLUG_ORG,
			convoyId: CONVOY,
			fahrzeuge: [konvoiFahrzeug({ vehicle: { id: 'v1', name: 'LF 10', callsign: 'Florian 1' } })],
		});
		await page.goto(`/o/${SLUG_ORG}/tracking/${CONVOY}`, { waitUntil: 'domcontentloaded' });

		const summe = page.getByTestId('verbandsstaerke');
		await expect(summe).not.toContainText('0/0/0//0');
		await expect(summe).toContainText('1 ohne Meldung');
	});
});

test.describe('Stärke nachtragen (Tracking-Ansicht)', () => {
	const SLUG_ORG = 'thw-musterstadt';
	const CONVOY = '11111111-1111-1111-1111-111111111111';

	/** Zwei Fahrzeuge: eines mit Soll und Meldung, eines nur mit Soll. */
	function verband() {
		return [
			konvoiFahrzeug({
				position: 1,
				staerke_soll_fuehrer: 0, staerke_soll_unterfuehrer: 1, staerke_soll_mannschaften: 8,
				staerke_ist_fuehrer: 0, staerke_ist_unterfuehrer: 1, staerke_ist_mannschaften: 6,
				vehicle: { id: 'v1', name: 'LF 10', callsign: 'Florian 1' },
			}),
			konvoiFahrzeug({
				position: 2,
				staerke_soll_fuehrer: 0, staerke_soll_unterfuehrer: 1, staerke_soll_mannschaften: 8,
				vehicle: { id: 'v2', name: 'MTW 2', callsign: 'Florian 2' },
			}),
		];
	}

	async function oeffnenAlsOrg(page: Page, rolle?: 'beobachter' | 'fahrer' | 'planer' | 'admin') {
		await blockExternal(page);
		const meldungen = await mockOrgPortal(page, {
			slug: SLUG_ORG, convoyId: CONVOY, fahrzeuge: verband(), rolle,
		});
		await page.goto(`/o/${SLUG_ORG}/tracking/${CONVOY}`, { waitUntil: 'domcontentloaded' });
		return meldungen;
	}

	test('die Führung trägt eine über Funk gemeldete Stärke für ein fremdes Fahrzeug nach', async ({ page }) => {
		const meldungen = await oeffnenAlsOrg(page);

		await page.getByTestId('staerke-edit-v2').click();
		const form = page.getByTestId('staerke-form-v2');
		await form.getByLabel('Führer', { exact: true }).fill('0');
		await form.getByLabel('Unterführer', { exact: true }).fill('1');
		await form.getByLabel('Mannschaften', { exact: true }).fill('7');

		// Tippen ist keine Meldung — auch hier nicht.
		expect(meldungen).toHaveLength(0);

		await form.getByRole('button', { name: /Stärke eintragen/ }).click();

		await expect.poll(() => meldungen.length).toBe(1);
		// An das Fahrzeug der Zeile, nicht an das erste im Verband.
		expect(meldungen[0]).toEqual({ fahrzeugId: 'v2', fuehrer: 0, unterfuehrer: 1, mannschaften: 7 });
		// Die Liste zeigt die Meldung sofort, ohne Neuladen.
		await expect(staerke(page, 'v2')).toContainText('0/1/7//8');
		// Und die Summe zählt sie mit: 0/1/6 + 0/1/7.
		await expect(page.getByTestId('verbandsstaerke')).toContainText('0/2/13//15');
	});

	test('die Felder starten bei der bestehenden Meldung — und ohne eine bei null, nicht beim Soll', async ({ page }) => {
		await oeffnenAlsOrg(page);

		// v1 hat gemeldet: die Korrektur beginnt bei dem, was gemeldet wurde.
		await page.getByTestId('staerke-edit-v1').click();
		const gemeldet = page.getByTestId('staerke-form-v1');
		await expect(gemeldet.getByLabel('Mannschaften', { exact: true })).toHaveValue('6');

		// v2 hat nur ein Soll (0/1/8). Stünde es in den Feldern, wäre die
		// bequemste Antwort „wie geplant" — und die Meldung wertlos.
		await page.getByTestId('staerke-edit-v2').click();
		const offen = page.getByTestId('staerke-form-v2');
		await expect(offen.getByLabel('Unterführer', { exact: true })).toHaveValue('0');
		await expect(offen.getByLabel('Mannschaften', { exact: true })).toHaveValue('0');
	});

	test('ein Beobachter sieht die Stärke, kann sie aber nicht setzen', async ({ page }) => {
		await oeffnenAlsOrg(page, 'beobachter');

		await expect(staerke(page, 'v1')).toContainText('0/1/6//7');
		await expect(page.getByTestId('staerke-edit-v1')).toHaveCount(0);

		await page.getByRole('button', { name: 'Status', exact: true }).click();
		await expect(page.getByTestId('staerke-form-eigen')).toHaveCount(0);
	});

	test('die eigene Stärke geht an das unter „Meine Position" gewählte Fahrzeug', async ({ page }) => {
		const meldungen = await oeffnenAlsOrg(page);

		await page.getByLabel('Meine Position').selectOption('v2');
		await page.getByRole('button', { name: 'Status', exact: true }).click();

		const form = page.getByTestId('staerke-form-eigen');
		await form.getByLabel('Führer', { exact: true }).fill('1');
		await form.getByLabel('Unterführer', { exact: true }).fill('0');
		await form.getByLabel('Mannschaften', { exact: true }).fill('5');
		await form.getByRole('button', { name: /Stärke melden/ }).click();

		await expect.poll(() => meldungen.length).toBe(1);
		expect(meldungen[0]).toEqual({ fahrzeugId: 'v2', fuehrer: 1, unterfuehrer: 0, mannschaften: 5 });
		await expect(form.getByText('Stärke gemeldet')).toBeVisible();
	});
});
