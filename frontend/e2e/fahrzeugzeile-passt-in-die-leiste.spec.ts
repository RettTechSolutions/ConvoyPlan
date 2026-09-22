import { test, expect, type Page } from '@playwright/test';
import {
	blockExternal, fahrzeug, konvoiFahrzeug, mockOrgPortal, mockTrack, position,
} from './fixtures';

/**
 * Die Zusage: **in der Fahrzeugliste verdeckt nichts etwas anderes.**
 *
 * Am Telefon ist die Seitenleiste eine Schublade von `min(320px, 85vw)`. In
 * eine Zeile gehören Name, Funkrufname, Sonderfunktion, „LIVE", die Stärke und
 * der Status — nebeneinander sind das mehr als 320 px. Solange die Zeile nicht
 * umbrechen durfte, schrumpfte nur der Name; alles dahinter lief weiter und
 * legte sich über die rechte Hälfte: das „LIVE"-Abzeichen stand mitten in der
 * Stärke, und beides war unlesbar.
 *
 * Geprüft wird deshalb Geometrie, nicht Text — ein `toContainText` sieht eine
 * Überlagerung nicht, und ein Bildschirmfoto sieht sie nur, wenn jemand
 * hinschaut.
 */

const SLUG_ORG = 'thw-musterstadt';
const CONVOY = '11111111-1111-1111-1111-111111111111';
const SLUG_TRACK = '6dA4KrUG';

/** Ein Telefon im Hochformat — dort ist die Leiste am engsten. */
const TELEFON = { width: 390, height: 844 };

/** Ein Fahrzeug mit allem, was eine Zeile tragen kann. */
const NAME = 'Akkon Peißenberg 10/1';
const FUNKRUFNAME = 'Akkon Pei 10/1';

type Kasten = { was: string; links: number; rechts: number; oben: number; unten: number };

/** Die sichtbaren Teile einer Fahrzeugzeile, als Kästen. */
async function kaesten(page: Page): Promise<Kasten[]> {
	return page.evaluate(() => {
		const zeile = document.querySelector('.vehicle-row');
		if (!zeile) throw new Error('Keine Fahrzeugzeile gefunden');
		const teile = [
			...zeile.querySelectorAll('.vname, .tag, .live-badge, .status-chip, .status-label, [data-testid^="staerke-"]'),
		] as HTMLElement[];
		return teile.map((el) => {
			const r = el.getBoundingClientRect();
			const klasse = el.getAttribute('data-testid') ?? el.className.split(' ')[0];
			return {
				was: `${klasse} „${(el.textContent ?? '').trim()}"`,
				links: r.left, rechts: r.right, oben: r.top, unten: r.bottom,
			};
		});
	});
}

/**
 * Paare, die sich überdecken. Eine Kante darf sich berühren (Rundung), eine
 * Überlappung von mehr als einem Pixel nicht.
 */
function ueberlagerungen(teile: Kasten[]): string[] {
	const treffer: string[] = [];
	for (let i = 0; i < teile.length; i++) {
		for (let j = i + 1; j < teile.length; j++) {
			const a = teile[i], b = teile[j];
			const quer = Math.min(a.rechts, b.rechts) - Math.max(a.links, b.links);
			const hoch = Math.min(a.unten, b.unten) - Math.max(a.oben, b.oben);
			if (quer > 1 && hoch > 1) treffer.push(`${a.was} ↔ ${b.was}`);
		}
	}
	return treffer;
}

/** Was über den rechten Rand der Leiste hinaussteht. */
async function ragtHinaus(page: Page, teile: Kasten[]): Promise<string[]> {
	const leiste = await page.locator('.sidebar').boundingBox();
	if (!leiste) throw new Error('Keine Seitenleiste gefunden');
	const rand = leiste.x + leiste.width + 1;
	return teile.filter((t) => t.rechts > rand).map((t) => t.was);
}

async function leisteOeffnen(page: Page) {
	await page.getByRole('button', { name: 'Menü', exact: true }).click();
	await expect(page.locator('.vehicle-row').first()).toBeVisible();
}

test.use({ viewport: TELEFON });

test.describe('Fahrzeugzeile am Telefon', () => {
	test('in der Tracking-Ansicht verdeckt kein Abzeichen ein anderes', async ({ page }) => {
		await blockExternal(page);
		await mockOrgPortal(page, {
			slug: SLUG_ORG,
			convoyId: CONVOY,
			fahrzeuge: [konvoiFahrzeug({
				vehicle_status: 'moving',
				staerke_ist_fuehrer: 0, staerke_ist_unterfuehrer: 1, staerke_ist_mannschaften: 1,
				vehicle: { id: 'v1', name: NAME, callsign: FUNKRUFNAME },
			})],
			positionen: [position('v1')],
		});
		await page.goto(`/o/${SLUG_ORG}/tracking/${CONVOY}`, { waitUntil: 'domcontentloaded' });
		await leisteOeffnen(page);

		// Erst wenn das Abzeichen da ist, ist die Zeile so voll wie im Einsatz.
		await expect(page.locator('.vehicle-row .live-badge')).toBeVisible();

		const teile = await kaesten(page);
		expect(ueberlagerungen(teile)).toEqual([]);
		expect(await ragtHinaus(page, teile)).toEqual([]);
	});

	test('im Fahrer-Link ebenso', async ({ page }) => {
		await blockExternal(page);
		await mockTrack(page, {
			scope: 'track',
			fahrzeuge: [fahrzeug({
				id: 'v1', name: NAME, callsign: FUNKRUFNAME, sonderfunktion: 'Führung',
				vehicle_status: 'moving',
				staerke_ist_fuehrer: 0, staerke_ist_unterfuehrer: 1, staerke_ist_mannschaften: 1,
			})],
			positionen: [position('v1')],
		});
		await page.goto(`/track/${SLUG_TRACK}`, { waitUntil: 'domcontentloaded' });
		await leisteOeffnen(page);

		await expect(page.locator('.vehicle-row .live-badge')).toBeVisible();

		const teile = await kaesten(page);
		expect(ueberlagerungen(teile)).toEqual([]);
		expect(await ragtHinaus(page, teile)).toEqual([]);
	});
});
