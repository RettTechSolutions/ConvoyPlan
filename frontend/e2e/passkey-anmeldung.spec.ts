import { test, expect, type CDPSession, type Page } from '@playwright/test';
import { createHash, createPublicKey, generateKeyPairSync, randomBytes, verify } from 'node:crypto';
import { blockExternal } from './fixtures';

/**
 * Die Zusagen der Passkey-Anmeldung an der Oberfläche.
 *
 * Ob eine Antwort gilt, entscheidet der Server, und das prüft
 * `backend/tests/test_passkey_anmeldung.py`. Was man dort nicht sieht, ist
 * der Weg durch den Browser: dass `$lib/passkey` die Bytes von
 * `navigator.credentials` unverändert als base64url weiterreicht — ein
 * vertauschtes Zeichen im Alphabet, und jede Signatur ist falsch, ohne dass
 * irgendwo ein Fehler stünde —, dass eine Anmeldung **ohne** E-Mail und
 * Passwort hinausgeht und in genau der Organisation der Seite, und dass beim
 * Einrichten das Passwort nur an die Optionen geht.
 *
 * Das Gerät ist Chromiums virtueller Authenticator (CDP `WebAuthn`), mit
 * Benutzerverifikation — so, wie der Server es verlangt.
 */

const SLUG = 'thw-musterstadt';
const CHALLENGE_ID = 'challenge-kennung-1';

const b64url = (b: Buffer) => b.toString('base64url');
const unb64url = (s: string) => Buffer.from(s, 'base64url');

async function geraet(page: Page): Promise<{ cdp: CDPSession; id: string }> {
	const cdp = await page.context().newCDPSession(page);
	await cdp.send('WebAuthn.enable');
	const { authenticatorId } = await cdp.send('WebAuthn.addVirtualAuthenticator', {
		options: {
			protocol: 'ctap2',
			transport: 'internal',
			hasResidentKey: true,
			hasUserVerification: true,
			isUserVerified: true,
			automaticPresenceSimulation: true,
		},
	});
	return { cdp, id: authenticatorId };
}

test.describe('Anmelden mit Passkey', () => {
	test('schickt nur die signierte Challenge — für genau diese Organisation', async ({ page }) => {
		const { cdp, id } = await geraet(page);
		const { privateKey, publicKey } = generateKeyPairSync('ec', { namedCurve: 'P-256' });
		const credentialId = randomBytes(16);
		const userHandle = randomBytes(16);
		await cdp.send('WebAuthn.addCredential', {
			authenticatorId: id,
			credential: {
				credentialId: credentialId.toString('base64'),
				isResidentCredential: true,
				rpId: 'localhost',
				privateKey: privateKey.export({ format: 'der', type: 'pkcs8' }).toString('base64'),
				userHandle: userHandle.toString('base64'),
				signCount: 0,
			},
		});

		const challenge = b64url(randomBytes(32));
		let angemeldet = false;
		let anmeldung: Record<string, unknown> | null = null;

		await blockExternal(page);
		// Alles, was die Planungsseite nach der Anmeldung lädt, ist hier nicht
		// Gegenstand — leer beantworten statt an ein Backend durchreichen.
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
		await page.route('**/api/auth/login/passkey/options', (r) =>
			r.fulfill({
				json: {
					challenge_id: CHALLENGE_ID,
					options: { challenge, timeout: 60000, rpId: 'localhost', allowCredentials: [], userVerification: 'required' },
				},
			}),
		);
		await page.route('**/api/auth/login/passkey', (r) => {
			anmeldung = JSON.parse(r.request().postData() ?? '{}');
			angemeldet = true;
			r.fulfill({ json: { access_token: 'x', token_type: 'bearer', mfa_required: false, mfa_token: null } });
		});

		await page.goto(`/o/${SLUG}/login`);
		await expect(page.getByRole('heading', { name: 'THW OV Musterstadt' })).toBeVisible();
		await page.getByRole('button', { name: 'Mit Passkey anmelden' }).click();
		await page.waitForURL(`**/o/${SLUG}/plan`);

		expect(anmeldung).not.toBeNull();
		const body = anmeldung as unknown as {
			challenge_id: string;
			org_slug: string;
			credential: { rawId: string; response: Record<string, string> };
		};
		// Keine Adresse, kein Passwort — nur Kennung, Antwort und Organisation.
		expect(Object.keys(body).sort()).toEqual(['challenge_id', 'credential', 'org_slug']);
		expect(body.challenge_id).toBe(CHALLENGE_ID);
		expect(body.org_slug).toBe(SLUG);
		expect(body.credential.rawId).toBe(b64url(credentialId));
		expect(body.credential.response.userHandle).toBe(b64url(userHandle));

		const clientData = JSON.parse(unb64url(body.credential.response.clientDataJSON).toString());
		expect(clientData).toMatchObject({ type: 'webauthn.get', challenge, origin: 'http://localhost:4173' });

		// Die Signatur stimmt über genau die Bytes, die angekommen sind — das
		// ist der Beweis, dass die Umwandlung nichts verfälscht.
		const authData = unb64url(body.credential.response.authenticatorData);
		const signiert = Buffer.concat([authData, createHash('sha256').update(unb64url(body.credential.response.clientDataJSON)).digest()]);
		const pub = createPublicKey(publicKey.export({ format: 'pem', type: 'spki' }));
		expect(verify('sha256', signiert, pub, unb64url(body.credential.response.signature))).toBe(true);
		// Benutzer anwesend und verifiziert (UP, UV).
		expect(authData[32] & 0x05).toBe(0x05);
	});
});

test.describe('Passkey einrichten', () => {
	const HUELLE = 'http://localhost:4174/?k=passkey';

	test('legt einen auffindbaren Passkey an; das Passwort geht nur an die Optionen', async ({ page }) => {
		const { cdp, id } = await geraet(page);
		await blockExternal(page);
		await page.goto(HUELLE);

		await expect(page.getByText('Noch kein Passkey eingerichtet.')).toBeVisible();
		await page.getByRole('button', { name: 'Passkey hinzufügen' }).click();
		await page.getByLabel('Aktuelles Passwort').fill('Mein-Passwort-1');
		await page.getByLabel('Name (optional)').fill('Diensthandy');
		await page.getByRole('button', { name: 'Weiter' }).click();

		await expect(page.locator('.liste li')).toHaveCount(1);
		await expect(page.locator('.liste .name')).toHaveText('Diensthandy');

		const aufrufe = (await page.evaluate(() => (window as unknown as { __passkeyAufrufe: unknown[] }).__passkeyAufrufe)) as {
			name: string;
			body: { password?: string; challenge_id?: string; name?: string; credential?: { response: Record<string, unknown> } };
		}[];
		expect(aufrufe.map((a) => a.name)).toEqual(['registerOptions', 'register']);
		expect(aufrufe[0].body.password).toBe('Mein-Passwort-1');
		const registrierung = aufrufe[1].body;
		expect(JSON.stringify(registrierung)).not.toContain('Mein-Passwort-1');
		expect(registrierung.challenge_id).toBe('ch-1');
		expect(registrierung.name).toBe('Diensthandy');
		expect(typeof registrierung.credential?.response.attestationObject).toBe('string');
		expect(Array.isArray(registrierung.credential?.response.transports)).toBe(true);

		const clientData = JSON.parse(unb64url(registrierung.credential?.response.clientDataJSON as string).toString());
		expect(clientData).toMatchObject({ type: 'webauthn.create', challenge: 'q2Vt8eYp3Lr7Wn1Kc5Xh9Zb4Md6Sf0Ga' });

		// Auf dem Gerät liegt er als auffindbarer Passkey — sonst ginge die
		// Anmeldung ohne E-Mail-Adresse später gar nicht.
		const { credentials } = await cdp.send('WebAuthn.getCredentials', { authenticatorId: id });
		expect(credentials).toHaveLength(1);
		expect(credentials[0].isResidentCredential).toBe(true);
		expect(credentials[0].rpId).toBe('localhost');
	});
});
