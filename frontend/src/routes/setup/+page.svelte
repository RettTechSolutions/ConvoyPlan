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

	// Step 3 — Branding
	let appName = $state('');
	let colorPrimary = $state('#E23D28');
	let colorPrimaryHover = $state('#C23020');
	let colorAccent = $state('#3498db');
	let colorBg = $state('#f5f3ee');
	let colorSurface = $state('#ffffff');
	let colorNavBg = $state('#2c3e50');
	let colorNavText = $state('#ecf0f1');
	let colorText = $state('#2c3e50');
	let colorTextMuted = $state('#7f8c8d');
	let showAdvancedColors = $state(false);
	let logoMainFile = $state<File | null>(null);
	let logoMainPreview = $state<string | null>(null);
	let logoHorizFile = $state<File | null>(null);
	let logoHorizPreview = $state<string | null>(null);

	function darken(hex: string, amount = 10): string {
		const r = parseInt(hex.slice(1, 3), 16) / 255;
		const g = parseInt(hex.slice(3, 5), 16) / 255;
		const b = parseInt(hex.slice(5, 7), 16) / 255;
		const max = Math.max(r, g, b), min = Math.min(r, g, b);
		let h = 0, s = 0, l = (max + min) / 2;
		if (max !== min) {
			const d = max - min;
			s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
			if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
			else if (max === g) h = ((b - r) / d + 2) / 6;
			else h = ((r - g) / d + 4) / 6;
		}
		l = Math.max(0, l - amount / 100);
		function hue2rgb(p: number, q: number, t: number) {
			if (t < 0) t += 1; if (t > 1) t -= 1;
			if (t < 1/6) return p + (q - p) * 6 * t;
			if (t < 1/2) return q;
			if (t < 2/3) return p + (q - p) * (2/3 - t) * 6;
			return p;
		}
		const q2 = l < 0.5 ? l * (1 + s) : l + s - l * s;
		const p2 = 2 * l - q2;
		const nr = Math.round(hue2rgb(p2, q2, h + 1/3) * 255);
		const ng = Math.round(hue2rgb(p2, q2, h) * 255);
		const nb = Math.round(hue2rgb(p2, q2, h - 1/3) * 255);
		return `#${[nr, ng, nb].map(x => x.toString(16).padStart(2, '0')).join('')}`;
	}

	function onPrimaryColorChange() {
		colorPrimaryHover = darken(colorPrimary, 10);
	}

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

	function onLogoMainChange(e: Event) {
		const file = (e.target as HTMLInputElement).files?.[0];
		if (!file) return;
		logoMainFile = file;
		logoMainPreview = URL.createObjectURL(file);
	}

	function onLogoHorizChange(e: Event) {
		const file = (e.target as HTMLInputElement).files?.[0];
		if (!file) return;
		logoHorizFile = file;
		logoHorizPreview = URL.createObjectURL(file);
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
			// 1. Create admin account + server config
			const setupResp = await fetch('/api/setup', {
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

			if (setupResp.status === 409) { error = 'Setup wurde bereits durchgeführt.'; return; }
			if (!setupResp.ok) {
				const data = await setupResp.json().catch(() => ({}));
				error = data.detail || 'Fehler beim Setup';
				return;
			}

			// 2. Login to get token for branding API
			const loginResp = await fetch('/api/auth/login', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ email, password }),
			});
			if (!loginResp.ok) {
				// Non-fatal: setup succeeded, branding will use defaults
				step = 4;
				return;
			}
			const { access_token: token } = await loginResp.json();

			// 3. Save branding text/colors
			await fetch('/api/branding', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
				body: JSON.stringify({
					app_name: appName || 'ConvoyPlan',
					color_primary: colorPrimary,
					color_primary_hover: colorPrimaryHover,
					color_accent: colorAccent,
					color_bg: colorBg,
					color_surface: colorSurface,
					color_nav_bg: colorNavBg,
					color_nav_text: colorNavText,
					color_text: colorText,
					color_text_muted: colorTextMuted,
				}),
			});

			// 4. Upload logos if selected
			if (logoMainFile) {
				const fd = new FormData();
				fd.append('file', logoMainFile);
				await fetch('/api/branding/logo/main', {
					method: 'POST',
					headers: { 'Authorization': `Bearer ${token}` },
					body: fd,
				});
			}
			if (logoHorizFile) {
				const fd = new FormData();
				fd.append('file', logoHorizFile);
				await fetch('/api/branding/logo/horizontal', {
					method: 'POST',
					headers: { 'Authorization': `Bearer ${token}` },
					body: fd,
				});
			}

			step = 4;
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
			<span class="step-dot" class:active={step >= 3} class:done={step > 3}>3</span>
			<span class="step-line"></span>
			<span class="step-dot" class:active={step >= 4}>4</span>
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
				<button class="btn-primary" onclick={nextStep}>Weiter →</button>
			</div>

		{:else if step === 3}
			<h2>Branding</h2>
			<p class="hint">Passe Aussehen und Namen an deine Organisation an. Dieser Schritt ist optional.</p>

			<div class="form-group">
				<label>App-Name</label>
				<input type="text" bind:value={appName} placeholder="z.B. Feuerwehr München" />
				<span class="field-hint">Leer lassen für "ConvoyPlan"</span>
			</div>

			<div class="form-group">
				<label>Hauptlogo (quadratisch)</label>
				{#if logoMainPreview}
					<img src={logoMainPreview} alt="Vorschau" class="logo-preview" />
				{/if}
				<input type="file" accept=".png,.jpg,.jpeg,.svg" onchange={onLogoMainChange} />
				<span class="field-hint">PNG, JPG oder SVG, max. 2 MB</span>
			</div>

			<div class="form-group">
				<label>Horizontales Logo</label>
				{#if logoHorizPreview}
					<img src={logoHorizPreview} alt="Vorschau" class="logo-preview" />
				{/if}
				<input type="file" accept=".png,.jpg,.jpeg,.svg" onchange={onLogoHorizChange} />
			</div>

			<div class="form-group color-group">
				<label>Primärfarbe</label>
				<div class="color-row">
					<input type="color" bind:value={colorPrimary} oninput={onPrimaryColorChange} class="color-input" />
					<span class="color-hex">{colorPrimary}</span>
				</div>
			</div>

			<details class="advanced-colors">
				<summary>Erweiterte Farben</summary>
				<div class="adv-colors-grid">
					<div class="form-group color-group">
						<label>Hover</label>
						<div class="color-row">
							<input type="color" bind:value={colorPrimaryHover} class="color-input" />
							<span class="color-hex">{colorPrimaryHover}</span>
						</div>
					</div>
					<div class="form-group color-group">
						<label>Akzentfarbe</label>
						<div class="color-row">
							<input type="color" bind:value={colorAccent} class="color-input" />
							<span class="color-hex">{colorAccent}</span>
						</div>
					</div>
					<div class="form-group color-group">
						<label>Hintergrund</label>
						<div class="color-row">
							<input type="color" bind:value={colorBg} class="color-input" />
							<span class="color-hex">{colorBg}</span>
						</div>
					</div>
					<div class="form-group color-group">
						<label>Oberfläche</label>
						<div class="color-row">
							<input type="color" bind:value={colorSurface} class="color-input" />
							<span class="color-hex">{colorSurface}</span>
						</div>
					</div>
					<div class="form-group color-group">
						<label>Navigationsleiste</label>
						<div class="color-row">
							<input type="color" bind:value={colorNavBg} class="color-input" />
							<span class="color-hex">{colorNavBg}</span>
						</div>
					</div>
					<div class="form-group color-group">
						<label>Nav-Text</label>
						<div class="color-row">
							<input type="color" bind:value={colorNavText} class="color-input" />
							<span class="color-hex">{colorNavText}</span>
						</div>
					</div>
					<div class="form-group color-group">
						<label>Text</label>
						<div class="color-row">
							<input type="color" bind:value={colorText} class="color-input" />
							<span class="color-hex">{colorText}</span>
						</div>
					</div>
					<div class="form-group color-group">
						<label>Gedämpfter Text</label>
						<div class="color-row">
							<input type="color" bind:value={colorTextMuted} class="color-input" />
							<span class="color-hex">{colorTextMuted}</span>
						</div>
					</div>
				</div>
			</details>

			<p class="powered-by-note">Powered by ConvoyPlan</p>

			<div class="btn-row">
				<button class="btn-secondary" onclick={() => step--}>← Zurück</button>
				<button class="btn-secondary" onclick={submit} disabled={loading}>Überspringen</button>
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
	.step-line { flex: 1; height: 2px; background: rgba(255,255,255,.12); max-width: 45px; }

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

	.logo-preview { max-height: 60px; max-width: 100%; margin-bottom: .5rem; border-radius: 4px; }

	.color-group .color-row { display: flex; align-items: center; gap: .5rem; }
	.color-input { width: 36px; height: 36px; padding: 0; border: none; border-radius: 4px; cursor: pointer; background: none; }
	.color-hex { font-size: .82rem; color: rgba(255,255,255,.6); font-family: monospace; }

	.advanced-colors { margin-bottom: 1rem; }
	.advanced-colors summary { font-size: .85rem; color: rgba(255,255,255,.65); cursor: pointer; margin-bottom: .75rem; }
	.adv-colors-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .25rem 1rem; }

	.powered-by-note { font-size: .72rem; color: rgba(255,255,255,.35); text-align: center; margin: .75rem 0 0; }

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
