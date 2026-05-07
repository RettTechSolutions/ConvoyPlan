<script lang="ts">
	import { goto } from '$app/navigation';
	import AppLogo from '$lib/components/AppLogo.svelte';

	type TlsMode = 'letsencrypt' | 'custom' | 'internal';

	let step = $state(1);
	let loading = $state(false);
	let error = $state('');

	// Step 1 — Account
	let email = $state('');
	let password = $state('');
	let passwordConfirm = $state('');

	// Step 2 — Server
	let domain = $state('');
	let tlsMode = $state<TlsMode>('letsencrypt');
	let acmeEmail = $state('');
	let certPem = $state('');
	let keyPem = $state('');

	function readFile(file: File): Promise<string> {
		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = () => resolve(reader.result as string);
			reader.onerror = reject;
			reader.readAsText(file);
		});
	}

	async function onCertUpload(e: Event) {
		const file = (e.target as HTMLInputElement).files?.[0];
		if (file) certPem = await readFile(file);
	}

	async function onKeyUpload(e: Event) {
		const file = (e.target as HTMLInputElement).files?.[0];
		if (file) keyPem = await readFile(file);
	}

	function validateStep1(): string {
		if (!email) return 'E-Mail ist erforderlich';
		if (password.length < 8) return 'Passwort muss mindestens 8 Zeichen haben';
		if (password !== passwordConfirm) return 'Passwörter stimmen nicht überein';
		return '';
	}

	function validateStep2(): string {
		if (!domain) return 'Domain ist erforderlich';
		if (!/^[a-zA-Z0-9._-]+$/.test(domain)) return 'Ungültiges Domain-Format';
		if (tlsMode === 'letsencrypt' && !acmeEmail) return 'E-Mail für Let\'s Encrypt ist erforderlich';
		if (tlsMode === 'custom' && (!certPem || !keyPem)) return 'Zertifikat und Schlüssel sind erforderlich';
		return '';
	}

	function nextStep() {
		error = '';
		const validationError = step === 1 ? validateStep1() : validateStep2();
		if (validationError) { error = validationError; return; }
		step++;
	}

	async function submit() {
		error = '';
		const validationError = validateStep1() || validateStep2();
		if (validationError) { error = validationError; step = 1; return; }

		loading = true;
		try {
			const resp = await fetch('/api/setup', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					email,
					password,
					domain,
					tls_mode: tlsMode,
					acme_email: acmeEmail || email,
					cert_pem: certPem,
					key_pem: keyPem,
				}),
			});

			if (resp.status === 409) {
				error = 'Setup wurde bereits durchgeführt.';
				return;
			}
			if (!resp.ok) {
				const data = await resp.json().catch(() => ({}));
				error = data.detail || 'Fehler beim Setup';
				return;
			}

			step = 3;
		} catch {
			error = 'Verbindungsfehler — bitte erneut versuchen';
		} finally {
			loading = false;
		}
	}
</script>

<div class="setup-page">
	<div class="setup-card">
		<div class="logo-area">
			<AppLogo variant="main" height={64} />
		</div>

		<div class="steps">
			<span class="step-dot" class:active={step >= 1} class:done={step > 1}>1</span>
			<span class="step-line"></span>
			<span class="step-dot" class:active={step >= 2} class:done={step > 2}>2</span>
			<span class="step-line"></span>
			<span class="step-dot" class:active={step >= 3}>3</span>
		</div>

		{#if error}
			<div class="error-bar">{error}</div>
		{/if}

		{#if step === 1}
			<h2>Admin-Account anlegen</h2>
			<p class="hint">Dieser Account hat vollen Zugriff auf alle Einstellungen.</p>
			<div class="form-group">
				<label>E-Mail</label>
				<input type="email" bind:value={email} placeholder="admin@example.com" autocomplete="username" />
			</div>
			<div class="form-group">
				<label>Passwort</label>
				<input type="password" bind:value={password} placeholder="Mindestens 8 Zeichen" autocomplete="new-password" />
			</div>
			<div class="form-group">
				<label>Passwort bestätigen</label>
				<input type="password" bind:value={passwordConfirm} placeholder="Passwort wiederholen" autocomplete="new-password" />
			</div>
			<button class="btn-primary" onclick={nextStep}>Weiter →</button>

		{:else if step === 2}
			<h2>Server konfigurieren</h2>
			<p class="hint">Wie ist dieser Server erreichbar?</p>

			<div class="form-group">
				<label>Domain / FQDN</label>
				<input type="text" bind:value={domain} placeholder="convoy.example.com" />
			</div>

			<div class="form-group">
				<label>SSL-Zertifikat</label>
				<div class="radio-group">
					<label class="radio-label">
						<input type="radio" bind:group={tlsMode} value="letsencrypt" />
						Automatisch (Let's Encrypt)
					</label>
					<label class="radio-label">
						<input type="radio" bind:group={tlsMode} value="custom" />
						Eigenes Zertifikat hochladen
					</label>
					<label class="radio-label">
						<input type="radio" bind:group={tlsMode} value="internal" />
						Intern / localhost (kein HTTPS)
					</label>
				</div>
			</div>

			{#if tlsMode === 'letsencrypt'}
				<div class="form-group">
					<label>E-Mail für Let's Encrypt</label>
					<input type="email" bind:value={acmeEmail} placeholder={email || 'admin@example.com'} />
					<span class="field-hint">Für Ablauf-Benachrichtigungen</span>
				</div>
			{/if}

			{#if tlsMode === 'custom'}
				<div class="form-group">
					<label>Zertifikat (cert.pem)</label>
					<input type="file" accept=".pem,.crt" onchange={onCertUpload} />
					{#if certPem}<span class="field-hint ok">✓ Geladen</span>{/if}
				</div>
				<div class="form-group">
					<label>Privater Schlüssel (key.pem)</label>
					<input type="file" accept=".pem,.key" onchange={onKeyUpload} />
					{#if keyPem}<span class="field-hint ok">✓ Geladen</span>{/if}
				</div>
			{/if}

			<div class="btn-row">
				<button class="btn-secondary" onclick={() => step--}>← Zurück</button>
				<button class="btn-primary" onclick={submit} disabled={loading}>
					{loading ? 'Wird eingerichtet…' : 'Einrichten'}
				</button>
			</div>

		{:else}
			<h2>Einrichtung abgeschlossen</h2>
			<p class="hint">
				ConvoyPlan ist einsatzbereit. Melde dich mit deinem Admin-Account an.
			</p>
			{#if domain && domain !== 'localhost'}
				<p class="hint">
					Domain: <strong>{domain}</strong> — Caddy wurde neu geladen.
					Let's Encrypt-Zertifikate werden in wenigen Sekunden ausgestellt.
				</p>
			{/if}
			<button class="btn-primary" onclick={() => goto('/login')}>Zum Login →</button>
		{/if}
	</div>
</div>

<style>
	:global(body) { margin: 0; font-family: system-ui, sans-serif; background: #0F1B24; color: white; }
	.setup-page { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 1rem; }
	.setup-card { background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.1); border-radius: 12px; padding: 2rem; width: 100%; max-width: 440px; }
	.logo-area { display: flex; justify-content: center; margin-bottom: 1.5rem; }

	.steps { display: flex; align-items: center; justify-content: center; gap: 0; margin-bottom: 1.5rem; }
	.step-dot { width: 28px; height: 28px; border-radius: 50%; border: 2px solid rgba(255,255,255,.2); display: flex; align-items: center; justify-content: center; font-size: .75rem; color: rgba(255,255,255,.4); }
	.step-dot.active { border-color: #6B7F4D; color: #a8c070; }
	.step-dot.done { background: #6B7F4D; border-color: #6B7F4D; color: white; }
	.step-line { flex: 1; height: 2px; background: rgba(255,255,255,.12); max-width: 60px; }

	h2 { margin: 0 0 .25rem; font-size: 1.15rem; }
	.hint { color: rgba(255,255,255,.55); font-size: .85rem; margin: 0 0 1.25rem; }
	.error-bar { background: rgba(194,48,32,.2); border: 1px solid #C23020; color: #ff9e93; padding: .5rem .75rem; border-radius: 6px; font-size: .85rem; margin-bottom: 1rem; }

	.form-group { margin-bottom: 1rem; }
	.form-group label { display: block; font-size: .82rem; color: rgba(255,255,255,.65); margin-bottom: .3rem; }
	.form-group input[type="email"],
	.form-group input[type="text"],
	.form-group input[type="password"] {
		width: 100%; box-sizing: border-box; padding: .5rem .7rem;
		background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.18);
		border-radius: 6px; color: white; font-size: .9rem;
	}
	.form-group input[type="email"]:focus,
	.form-group input[type="text"]:focus,
	.form-group input[type="password"]:focus { outline: none; border-color: #6B7F4D; }

	.form-group input[type="file"] { font-size: .85rem; color: rgba(255,255,255,.7); }

	.radio-group { display: flex; flex-direction: column; gap: .4rem; }
	.radio-label { display: flex; align-items: center; gap: .5rem; font-size: .88rem; color: rgba(255,255,255,.8); cursor: pointer; }
	.radio-label input[type="radio"] { accent-color: #6B7F4D; }

	.field-hint { font-size: .76rem; color: rgba(255,255,255,.45); display: block; margin-top: .2rem; }
	.field-hint.ok { color: #a8c070; }

	.btn-primary { width: 100%; padding: .6rem 1rem; background: #6B7F4D; border: none; border-radius: 6px; color: white; font-size: .95rem; font-weight: 600; cursor: pointer; margin-top: .5rem; }
	.btn-primary:hover:not(:disabled) { background: #7a9158; }
	.btn-primary:disabled { opacity: .5; cursor: not-allowed; }
	.btn-secondary { padding: .6rem 1rem; background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.2); border-radius: 6px; color: white; font-size: .9rem; cursor: pointer; }
	.btn-row { display: flex; gap: .75rem; margin-top: .5rem; }
	.btn-row .btn-primary { flex: 1; margin-top: 0; }
</style>
