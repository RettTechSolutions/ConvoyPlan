import { test, expect, type Page } from '@playwright/test';

// Einrichten eines Trackers per USB aus dem Org-Admin (Web Serial). Zusagen, die man
// einem Bildschirmfoto nicht ansieht:
//
// - Aufs Gerät gehen genau die Adresse dieser Instanz und der Einmal-Code — kein Token,
//   nichts aus der Sitzung. Eigene Wurzelzertifikate nur, wenn welche eingefügt sind,
//   und nur die PEM-Blöcke daraus.
// - Ein Fehler des Geräts (hier: Zertifikat nicht prüfbar) lässt den Code stehen; man
//   kann es noch einmal versuchen. Nach dem Erfolg ist der Code weg.
// - Ohne Web Serial gibt es den Knopf nicht, sondern einen Hinweis.
//
// Das Gerät ist nachgebaut, wie `simulator/tracker_sim/usb.py` im Repo ConvoyPlan-Tracker
// antwortet: Startmeldung ohne JSON vorweg, Zwischenstände, eine Schlusszeile mit `ok`,
// und Zeilen, die in Stücken ankommen.

const HUELLE = 'http://localhost:4174/?k=tracker';
const PEM = '-----BEGIN CERTIFICATE-----\nMIIBszCCAVmgAwIBAgIU\n-----END CERTIFICATE-----';

type Verhalten = { fehler?: 'tls' | 'code_abgelehnt'; eingerichtetFuer?: string };

async function geraetAnstecken(page: Page, verhalten: Verhalten = {}) {
	await page.addInitScript((v: Verhalten) => {
		const enc = new TextEncoder();
		const dec = new TextDecoder();
		const w = window as unknown as Record<string, unknown>;
		w.__usbGesendet = [];
		let ctrl!: ReadableStreamDefaultController<Uint8Array>;
		// Eine Zeile in zwei Stücken, damit das Zusammensetzen mitgeprüft wird.
		const senden = (o: object) => {
			const b = enc.encode(JSON.stringify(o) + '\n');
			const h = Math.floor(b.length / 2);
			ctrl.enqueue(b.slice(0, h));
			setTimeout(() => ctrl.enqueue(b.slice(h)), 5);
		};
		let puffer = '';
		const port = {
			readable: new ReadableStream<Uint8Array>({ start: (c) => { ctrl = c; } }),
			writable: new WritableStream<Uint8Array>({
				write(stueck) {
					puffer += dec.decode(stueck);
					let i: number;
					while ((i = puffer.indexOf('\n')) >= 0) {
						const anfrage = JSON.parse(puffer.slice(0, i));
						puffer = puffer.slice(i + 1);
						(w.__usbGesendet as object[]).push(anfrage);
						if (anfrage.befehl === 'info') {
							ctrl.enqueue(enc.encode('*** Booting ConvoyPlan Tracker ***\r\n'));
							senden({
								ok: true, protokoll: 1, hardware_id: '352656100000009', hardware: 'nrf9151-v1',
								firmware: '0.2.0', eingerichtet: !!v.eingerichtetFuer, instanz: v.eingerichtetFuer ?? null,
							});
						} else if (anfrage.befehl === 'einrichten') {
							senden({ schritt: 'netz' });
							setTimeout(() => {
								senden({ schritt: 'einloesen' });
								setTimeout(() => senden(v.fehler
									? { ok: false, fehler: v.fehler, text: 'unknown ca' }
									: { ok: true, geraet_id: 't-neu' }), 20);
							}, 20);
						}
					}
				},
			}),
			async open(o: { baudRate: number }) { w.__usbBaud = o.baudRate; },
			async close() { w.__usbGeschlossen = true; },
		};
		Object.defineProperty(navigator, 'serial', { value: { requestPort: async () => port }, configurable: true });
	}, verhalten);
}

async function anlegen(page: Page) {
	await page.goto(HUELLE);
	await expect(page.getByTestId('tracker')).toHaveCount(1);
	await page.getByRole('button', { name: '+ Neuer Tracker' }).click();
	const form = page.getByRole('form', { name: 'Tracker' });
	await form.getByLabel('Name').fill('Tracker HLF 20');
	await form.getByRole('button', { name: 'Anlegen' }).click();
	await expect(page.getByTestId('neuer-code').locator('pre')).toHaveText('K7Q2-M9XD');
}

const gesendet = (page: Page) => page.evaluate(() => (window as unknown as { __usbGesendet: object[] }).__usbGesendet);

test('Per USB einrichten schreibt Adresse und Code aufs Gerät, sonst nichts', async ({ page }) => {
	await geraetAnstecken(page);
	await anlegen(page);
	await page.getByRole('button', { name: 'Per USB einrichten' }).click();

	await expect(page.getByRole('status').filter({ hasText: 'ist eingerichtet' })).toContainText(
		'Gerät 352656100000009, Firmware 0.2.0'
	);
	// Der Code ist verbraucht und verschwindet.
	await expect(page.getByTestId('neuer-code')).toHaveCount(0);
	await expect(page.locator('body')).not.toContainText('K7Q2-M9XD');

	expect(await gesendet(page)).toEqual([
		{ befehl: 'info' },
		{ befehl: 'einrichten', instanz: 'http://localhost:4174', code: 'K7Q2-M9XD' },
	]);
	expect(await page.evaluate(() => (window as unknown as { __usbGeschlossen?: boolean }).__usbGeschlossen)).toBe(true);
});

test('eine eigene Wurzel geht mit, der Text drumherum nicht', async ({ page }) => {
	await geraetAnstecken(page);
	await anlegen(page);
	await page.getByText('Eigene Zertifizierungsstelle').click();
	await page.getByLabel('Wurzelzertifikate').fill(`Unsere Stamm-CA:\n${PEM}\nbitte nicht weitergeben`);
	await expect(page.getByTestId('usb-einrichten')).toContainText('1 Zertifikat erkannt');
	await page.getByRole('button', { name: 'Per USB einrichten' }).click();
	await expect(page.getByTestId('neuer-code')).toHaveCount(0);

	const einrichten = (await gesendet(page))[1] as { wurzeln?: string[] };
	expect(einrichten.wurzeln).toEqual([PEM]);
});

test('scheitert das Zertifikat, bleibt der Code stehen und der Hinweis nennt den Ausweg', async ({ page }) => {
	await geraetAnstecken(page, { fehler: 'tls', eingerichtetFuer: 'https://alt.example.org' });
	await anlegen(page);
	await page.getByRole('button', { name: 'Per USB einrichten' }).click();

	const meldung = page.getByTestId('usb-einrichten').getByRole('alert');
	await expect(meldung).toContainText('Zertifikat dieser Instanz nicht prüfen');
	await expect(meldung).toContainText('bisher eingerichtet für https://alt.example.org');
	await expect(page.getByTestId('neuer-code').locator('pre')).toHaveText('K7Q2-M9XD');
	// Noch einmal versuchen geht.
	await expect(page.getByRole('button', { name: 'Per USB einrichten' })).toBeEnabled();
});

test('ohne Web Serial gibt es keinen Knopf, sondern einen Hinweis', async ({ page }) => {
	await page.addInitScript(() => {
		Object.defineProperty(navigator, 'serial', { value: undefined, configurable: true });
	});
	await anlegen(page);
	await expect(page.getByRole('button', { name: 'Per USB einrichten' })).toHaveCount(0);
	await expect(page.getByTestId('usb-einrichten')).toContainText('Chrome oder Edge');
});
