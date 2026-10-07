import { test, expect, type Page } from '@playwright/test';
import { blockExternal } from './fixtures';

/**
 * Passkey-Autofill auf der Anmeldeseite: die Zusagen der Ablaufsteuerung.
 *
 * Das Vorschlagsmenü am E-Mail-Feld gehört dem Browser, kein Test kann darauf
 * klicken. Deshalb steht hier `navigator.credentials.get` durch einen Stub
 * ersetzt, der jede Anfrage festhält und sich von außen beantworten lässt.
 * Dass die Bytes einer echten Antwort heil beim Server ankommen, prüft
 * `passkey-anmeldung.spec.ts` mit Chromiums virtuellem Authenticator; hier
 * geht es um das, was man einer Anmeldeseite nicht ansieht und was still
 * kaputtgehen kann:
 *
 * - beim Laden wartet genau eine stille Anfrage (`mediation: 'conditional'`),
 *   und das E-Mail-Feld kündigt Passkeys an (`autocomplete="… webauthn"`);
 * - wer einen Vorschlag wählt, ist ohne Passwort angemeldet;
 * - der Knopf beendet die stille Anfrage, **bevor** er seine eigene stellt —
 *   zwei offene lehnt der Browser ab;
 * - vor Ablauf der Challenge am Server wird die Anfrage mit frischer erneuert;
 * - lehnt der Server ab, steht die Meldung da und das Autofill bleibt;
 * - ein Browser, der sofort ablehnt, bringt die Seite nicht dazu, im Kreis
 *   Challenges abzurufen.
 */

const SLUG = 'thw-musterstadt';
const ERNEUERN_MS = 100_000; // AUTOFILL_ERNEUERN_MS in $lib/passkey

/** Die n-te Challenge, wie der Server sie schickt: base64url. */
const challenge = (n: number) => Buffer.from(`challenge-${n}`).toString('base64url');

type Anfrage = { mediation: string | null; challenge: string; aborted: boolean };

async function stubCredentials(page: Page, opts: { sofortAblehnen?: boolean } = {}) {
	await page.addInitScript((sofortAblehnen) => {
		type Eintrag = {
			mediation: string | null; challenge: string; aborted: boolean;
			resolve: (v: unknown) => void; reject: (e: unknown) => void;
		};
		const w = window as unknown as {
			__anfragen: Eintrag[];
			__antworten: (i: number) => void;
			PublicKeyCredential: unknown;
		};
		w.__anfragen = [];
		const zuText = (b: ArrayBuffer) =>
			btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
		const puffer = (text: string) => new TextEncoder().encode(text).buffer;

		if (typeof w.PublicKeyCredential !== 'function') w.PublicKeyCredential = function () {};
		(w.PublicKeyCredential as { isConditionalMediationAvailable?: () => Promise<boolean> })
			.isConditionalMediationAvailable = async () => true;

		Object.defineProperty(navigator.credentials, 'get', {
			configurable: true,
			value: (o: CredentialRequestOptions) =>
				new Promise((resolve, reject) => {
					const eintrag: Eintrag = {
						mediation: (o.mediation as string | undefined) ?? null,
						challenge: zuText(o.publicKey!.challenge as ArrayBuffer),
						aborted: false,
						resolve,
						reject,
					};
					w.__anfragen.push(eintrag);
					if (sofortAblehnen) {
						reject(new DOMException('abgelehnt', 'NotAllowedError'));
						return;
					}
					o.signal?.addEventListener('abort', () => {
						eintrag.aborted = true;
						reject(new DOMException('abgebrochen', 'AbortError'));
					});
				}),
		});

		w.__antworten = (i: number) =>
			w.__anfragen[i].resolve({
				id: 'Y3JlZA',
				rawId: puffer('cred'),
				type: 'public-key',
				authenticatorAttachment: 'platform',
				getClientExtensionResults: () => ({}),
				response: {
					clientDataJSON: puffer('{}'),
					authenticatorData: puffer('auth'),
					signature: puffer('sig'),
					userHandle: null,
				},
			});
	}, opts.sofortAblehnen ?? false);
}

/** Die Anmeldeseite mit gemockter API; zählt Options-Abrufe und Anmeldungen. */
async function seite(page: Page, opts: { serverLehntAb?: boolean } = {}) {
	const zaehler = { optionen: 0, anmeldungen: [] as Record<string, unknown>[] };
	let angemeldet = false;

	await blockExternal(page);
	await page.route('**/api/**', (r) => r.fulfill({ status: 404, json: { detail: 'Not Found' } }));
	await page.route('**/api/auth/org-lookup**', (r) => r.fulfill({ json: { name: 'THW OV Musterstadt', slug: SLUG } }));
	await page.route('**/api/auth/me', (r) =>
		angemeldet
			? r.fulfill({
				json: {
					user_id: 'u2', email: 'planer@example.org', is_superadmin: false,
					org_id: 'o1', org_slug: SLUG, org_name: 'THW OV Musterstadt', role: 'planer', is_demo: false,
				},
			})
			: r.fulfill({ status: 401, json: { detail: 'Not authenticated' } }),
	);
	await page.route('**/api/auth/login/passkey/options', (r) => {
		zaehler.optionen += 1;
		r.fulfill({
			json: {
				challenge_id: `kennung-${zaehler.optionen}`,
				options: { challenge: challenge(zaehler.optionen), rpId: 'localhost', userVerification: 'required' },
			},
		});
	});
	await page.route('**/api/auth/login/passkey', (r) => {
		zaehler.anmeldungen.push(JSON.parse(r.request().postData() ?? '{}'));
		if (opts.serverLehntAb) {
			r.fulfill({ status: 401, json: { detail: 'Invalid credentials' } });
			return;
		}
		angemeldet = true;
		r.fulfill({ json: { access_token: 'x', token_type: 'bearer', mfa_required: false, mfa_token: null } });
	});
	return zaehler;
}

const anfragen = (page: Page) =>
	page.evaluate(() =>
		(window as unknown as { __anfragen: Anfrage[] }).__anfragen.map(({ mediation, challenge, aborted }) => ({
			mediation, challenge, aborted,
		})),
	);

async function oeffnen(page: Page) {
	await page.goto(`/o/${SLUG}/login`);
	await expect(page.getByRole('heading', { name: 'THW OV Musterstadt' })).toBeVisible();
	await expect.poll(async () => (await anfragen(page)).length).toBe(1);
}

test.describe('Passkey-Autofill', () => {
	test('beim Laden wartet eine stille Anfrage; ein gewählter Vorschlag meldet an', async ({ page }) => {
		await stubCredentials(page);
		const zaehler = await seite(page);
		await oeffnen(page);

		await expect(page.locator('#email')).toHaveAttribute('autocomplete', /\bwebauthn$/);
		expect(await anfragen(page)).toEqual([{ mediation: 'conditional', challenge: challenge(1), aborted: false }]);

		await page.evaluate(() => (window as unknown as { __antworten: (i: number) => void }).__antworten(0));
		await page.waitForURL(`**/o/${SLUG}/plan`);

		expect(zaehler.anmeldungen).toHaveLength(1);
		expect(zaehler.anmeldungen[0]).toMatchObject({ challenge_id: 'kennung-1', org_slug: SLUG });
		expect(Object.keys(zaehler.anmeldungen[0]).sort()).toEqual(['challenge_id', 'credential', 'org_slug']);
	});

	test('der Knopf beendet die stille Anfrage, bevor er seine eigene stellt', async ({ page }) => {
		await stubCredentials(page);
		await seite(page);
		await oeffnen(page);

		await page.getByRole('button', { name: 'Mit Passkey anmelden' }).click();
		await expect.poll(async () => (await anfragen(page)).length).toBe(2);
		const [still, knopf] = await anfragen(page);
		expect(still).toMatchObject({ mediation: 'conditional', aborted: true });
		expect(knopf).toMatchObject({ mediation: null, aborted: false });
		expect(knopf.challenge).not.toBe(still.challenge);
	});

	test('vor Ablauf der Challenge wird die Anfrage mit frischer erneuert', async ({ page }) => {
		await page.clock.install();
		await stubCredentials(page);
		const zaehler = await seite(page);
		await oeffnen(page);

		await page.clock.fastForward(ERNEUERN_MS);
		await expect.poll(async () => (await anfragen(page)).length).toBe(2);
		const [alt, neu] = await anfragen(page);
		expect(alt.aborted).toBe(true);
		expect(neu).toMatchObject({ mediation: 'conditional', aborted: false, challenge: challenge(2) });
		expect(zaehler.optionen).toBe(2);
	});

	test('lehnt der Server ab, steht die Meldung da und das Autofill bleibt', async ({ page }) => {
		await stubCredentials(page);
		await seite(page, { serverLehntAb: true });
		await oeffnen(page);

		await page.evaluate(() => (window as unknown as { __antworten: (i: number) => void }).__antworten(0));
		await expect(page.locator('.error')).toBeVisible();
		await expect.poll(async () => (await anfragen(page)).length).toBe(2);
		expect((await anfragen(page))[1]).toMatchObject({ mediation: 'conditional', aborted: false });
	});

	test('ein Browser, der sofort ablehnt, löst keine Schleife aus', async ({ page }) => {
		await stubCredentials(page, { sofortAblehnen: true });
		const zaehler = await seite(page);
		await oeffnen(page);

		await page.waitForTimeout(1_500);
		expect((await anfragen(page)).length).toBe(1);
		expect(zaehler.optionen).toBe(1);
		// Der Knopf bleibt der Weg.
		await expect(page.getByRole('button', { name: 'Mit Passkey anmelden' })).toBeEnabled();
	});
});
