import { test, expect, type Page } from '@playwright/test';

// Kartenregion im Admin-Portal: Baut GraphHopper seinen Graphen außerhalb
// eines Regionswechsels (nach Update, Neustart ohne fertigen Graphen), steht
// das über der Region — sonst sähe der Betreiber nur „Routing offline". Die
// Zusagen:
//  - ein laufender Import nennt seine Dauer und die Frist, nach der er als
//    hängend gilt — es gibt keinen Lebensbeweis, die Frist ist die Grenze;
//  - ein hängender Import ist als solcher erkennbar und sagt, wo die Ursache
//    steht und dass ein Neustart neu baut;
//  - ohne Bau steht nichts da, und die Region bleibt wechselbar.

const HUELLE = 'http://localhost:4174';
const hinweis = (page: Page) => page.locator('.graph-build');

async function oeffnen(page: Page, bau: string) {
	await page.goto(`${HUELLE}/?k=region&bau=${bau}`);
	await expect(page.getByText('dach-latest.osm.pbf')).toBeVisible();
}

test('ein laufender Import nennt Dauer und Frist', async ({ page }) => {
	await oeffnen(page, 'import');

	await expect(hinweis(page)).toContainText('Routing-Graph wird neu aufgebaut');
	await expect(hinweis(page)).toContainText('seit 12 Min.');
	await expect(hinweis(page)).toContainText('Ohne Abschluss nach 4 Std. gilt der Import als hängend');
});

test('ein laufender Download hat keine erfundene Dauer', async ({ page }) => {
	await oeffnen(page, 'download');

	await expect(hinweis(page)).toContainText('Kartendaten werden heruntergeladen');
	await expect(hinweis(page)).not.toContainText(/seit \d/);
});

test('ein hängender Import sagt, wo die Ursache steht', async ({ page }) => {
	await oeffnen(page, 'haengt');

	await expect(hinweis(page)).toContainText('Import ohne Abschluss');
	await expect(hinweis(page)).toContainText('seit 5,0 Std.');
	await expect(hinweis(page)).toContainText('docker compose logs graphhopper');
});

test('ohne Bau steht nichts da', async ({ page }) => {
	await oeffnen(page, 'keiner');

	await expect(hinweis(page)).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Region wechseln' })).toBeVisible();
});
