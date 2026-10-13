import { test, expect } from '@playwright/test';
import { GRUNDLAGE, MITGLIEDER, ORG, ORGS, SLUG, BENUTZER, mockApi, tab } from './kontextmenue-attrappe';

// Module je Organisation (backend/app/services/org_module.py): der Betreiber
// schaltet frei, der Org-Admin sieht gesperrte Module als ausgegrauten Reiter.
//
// Die Zusagen, die man einem Bildschirmfoto nicht ansieht:
// - ein gesperrtes Modul fragt seine API gar nicht erst an — kein Fehlerbalken
//   aus einem 403, sondern die Erklärung, wer es freischaltet;
// - ein Klick im Adminportal schickt genau dieses eine Modul, nicht den
//   ganzen Satz (sonst überschriebe ein veralteter Stand eine Freigabe, die ein
//   anderer Superadmin gerade gesetzt hat).

const MODULE_TEILWEISE = { tracker: false, aktionsseiten: true, branding: true, ki: false };

test('Org-Admin: gesperrtes Modul ist ausgegraut und lädt nichts', async ({ page }) => {
	const angefragt: string[] = [];
	page.on('request', (r) => angefragt.push(new URL(r.url()).pathname));
	await mockApi(page, {
		...GRUNDLAGE,
		[`GET /api/organizations/${ORG}/members`]: MITGLIEDER,
		'GET /api/org/modules': MODULE_TEILWEISE,
	});
	await page.goto(`/o/${SLUG}/admin`, { waitUntil: 'domcontentloaded' });
	await expect(page.getByRole('cell', { name: 'anna@example.org' })).toBeVisible();

	await expect(tab(page, 'Tracker')).toHaveClass(/inaktiv/);
	await expect(tab(page, 'Tracker')).toContainText('🔒');
	await expect(tab(page, 'KI-Zugriff')).toHaveClass(/inaktiv/);
	await expect(tab(page, 'Aktionsseiten')).not.toHaveClass(/inaktiv/);
	await expect(tab(page, 'Branding')).not.toHaveClass(/inaktiv/);

	await tab(page, 'Tracker').click();
	await expect(page.getByTestId('modul-gesperrt')).toContainText('nicht freigeschaltet');
	await tab(page, 'KI-Zugriff').click();
	await expect(page.getByTestId('modul-gesperrt')).toContainText('KI-Zugriff');

	expect(angefragt.filter((p) => p.startsWith('/api/org/geraete') || p.startsWith('/api/org/mcp'))).toEqual([]);
});

test('Org-Admin: ohne Auskunft über Module bleibt alles bedienbar', async ({ page }) => {
	// Ein Backend ohne /api/org/modules (404): durchgesetzt wird dort, die Ansicht sperrt nichts.
	await mockApi(page, {
		...GRUNDLAGE,
		[`GET /api/organizations/${ORG}/members`]: MITGLIEDER,
	});
	await page.goto(`/o/${SLUG}/admin`, { waitUntil: 'domcontentloaded' });
	await expect(page.getByRole('cell', { name: 'anna@example.org' })).toBeVisible();
	await expect(page.locator('.tab.inaktiv')).toHaveCount(0);
});

test('Adminportal: ein Klick schaltet genau ein Modul frei', async ({ page }) => {
	let stand = { ...MODULE_TEILWEISE };
	const aufrufe = await mockApi(page, {
		...GRUNDLAGE,
		'GET /api/admin/users': BENUTZER,
		'GET /api/admin/organizations': ORGS,
		'GET /api/admin/modules/catalog': {
			module: [
				{ modul: 'tracker', label: 'Tracker', beschreibung: 'Feste Ortungsgeräte an Fahrzeugen' },
				{ modul: 'aktionsseiten', label: 'Aktionsseiten', beschreibung: 'Konvois öffentlich zeigen' },
				{ modul: 'branding', label: 'Branding', beschreibung: 'Eigenes Logo und eigene Farben' },
				{ modul: 'ki', label: 'KI-Zugriff', beschreibung: 'Zugriff über die MCP-Schnittstelle' },
			],
			standard: false,
			betriebsart: 'hosting',
		},
		'GET /api/admin/modules/organizations': () => [
			{ organization_id: ORG, organization_name: ORGS[0].name, organization_slug: ORGS[0].slug, is_demo: false, module: stand },
		],
		[`PUT /api/admin/modules/organizations/${ORG}`]: (req: { postDataJSON: () => Record<string, boolean> }) => {
			stand = { ...stand, ...req.postDataJSON() };
			return { organization_id: ORG, organization_name: ORGS[0].name, organization_slug: ORGS[0].slug, is_demo: false, module: stand };
		},
	});
	await page.goto('/admin', { waitUntil: 'domcontentloaded' });
	await tab(page, 'Organisationen').click();

	const zeile = page.getByRole('row', { name: /THW OV Musterstadt/ });
	const tracker = zeile.locator('.modul-chip', { hasText: 'Tracker' });
	await expect(tracker).toHaveAttribute('aria-pressed', 'false');
	await expect(page.getByText('zunächst keine Module')).toBeVisible();

	await tracker.click();
	await expect.poll(() => aufrufe).toEqual([
		{ methode: 'PUT', pfad: `/api/admin/modules/organizations/${ORG}`, koerper: { tracker: true } },
	]);
	await expect(tracker).toHaveAttribute('aria-pressed', 'true');
});
