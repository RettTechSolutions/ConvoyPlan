<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth';
	import { authApi } from '$lib/api';
	import AppLogo from '$lib/components/AppLogo.svelte';
	import { versionStore } from '$lib/stores/version.svelte';

	let email = $state('');
	let password = $state('');
	let error = $state('');
	let loading = $state(false);

	// MFA step
	let mfaRequired = $state(false);
	let mfaToken = $state('');
	let mfaCode = $state('');

	// Passwort-vergessen
	let forgotOpen = $state(false);
	let forgotEmail = $state('');
	let forgotWorking = $state(false);
	let forgotMessage = $state('');

	async function handleForgot(e: Event) {
		e.preventDefault();
		if (!forgotEmail) return;
		forgotWorking = true;
		forgotMessage = '';
		try {
			await authApi.requestPasswordReset(forgotEmail);
		} catch {
			// Antwort wird absichtlich nicht ausgewertet — 202 selbst bei unbekanntem Konto.
		} finally {
			forgotWorking = false;
			forgotMessage = 'Falls ein Konto mit dieser E-Mail existiert, wurde ein neues Passwort verschickt.';
		}
	}

	function openForgot() {
		forgotOpen = true;
		forgotEmail = email;
		forgotMessage = '';
	}

	async function handleLogin(e: Event) {
		e.preventDefault();
		loading = true;
		error = '';
		try {
			const result = await auth.login(email, password);
			if (result.mfa_required) {
				mfaRequired = true;
				mfaToken = result.mfa_token;
			} else {
				goto('/admin');
			}
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Login fehlgeschlagen';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		versionStore.load();
	});

	async function handleMfa(e: Event) {
		e.preventDefault();
		loading = true;
		error = '';
		try {
			await auth.mfaVerify(mfaToken, mfaCode);
			goto('/admin');
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Ungültiger Code';
		} finally {
			loading = false;
		}
	}
</script>

<div class="login-container">
	<div class="login-card">
		<div class="login-logo">
			<AppLogo variant="main" height={170} />
		</div>

		{#if !mfaRequired && !forgotOpen}
			<form onsubmit={handleLogin}>
				<div class="field">
					<label for="email">E-Mail</label>
					<input id="email" type="email" bind:value={email} required autocomplete="email" />
				</div>
				<div class="field">
					<label for="password">Passwort</label>
					<input id="password" type="password" bind:value={password} required autocomplete="current-password" />
				</div>
				{#if error}
					<p class="error">{error}</p>
				{/if}
				<button type="submit" disabled={loading}>
					{loading ? 'Anmelden…' : 'Anmelden'}
				</button>
				<button type="button" class="btn-link" onclick={openForgot}>Passwort vergessen?</button>
			</form>
		{:else if forgotOpen}
			<form onsubmit={handleForgot}>
				<p class="mfa-hint">Wir senden dir ein neues Passwort an deine E-Mail.</p>
				<div class="field">
					<label for="forgot-email">E-Mail</label>
					<input id="forgot-email" type="email" bind:value={forgotEmail} required autocomplete="email" />
				</div>
				{#if forgotMessage}
					<p class="info">{forgotMessage}</p>
				{/if}
				<button type="submit" disabled={forgotWorking || !forgotEmail}>
					{forgotWorking ? 'Sende…' : 'Neues Passwort anfordern'}
				</button>
				<button type="button" class="btn-back" onclick={() => { forgotOpen = false; forgotMessage = ''; }}>
					← Zurück zum Login
				</button>
			</form>
		{:else}
			<form onsubmit={handleMfa}>
				<p class="mfa-hint">Gib den 6-stelligen Code aus deiner Authenticator-App ein.</p>
				<div class="field">
					<label for="mfa-code">Authentifizierungscode</label>
					<input
						id="mfa-code"
						type="text"
						inputmode="numeric"
						pattern="[0-9]*"
						maxlength="6"
						bind:value={mfaCode}
						required
						autocomplete="one-time-code"
						placeholder="000000"
					/>
				</div>
				{#if error}
					<p class="error">{error}</p>
				{/if}
				<button type="submit" disabled={loading || mfaCode.length < 6}>
					{loading ? 'Prüfe…' : 'Bestätigen'}
				</button>
				<button type="button" class="btn-back" onclick={() => { mfaRequired = false; mfaCode = ''; error = ''; }}>
					← Zurück
				</button>
			</form>
		{/if}

		<p class="org-hint">Organisationsmitglied? <a href="/">Hier Org-Code eingeben →</a></p>
		<p class="build-info">
			{#if versionStore.data.sha}
				v{__APP_VERSION__} · {versionStore.data.sha}
			{:else}
				v{__APP_VERSION__}
			{/if}
		</p>
	</div>
</div>

<style>
	.login-container {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 100vh;
		background: var(--bg);
	}
	.login-card {
		background: var(--surface-1);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 2.5rem;
		width: 100%;
		max-width: 380px;
		box-shadow: var(--shadow);
	}
	.login-logo { display: flex; justify-content: center; margin-bottom: 1.5rem; }
	h1 { display: none; }
	.field { margin-bottom: 1rem; }
	label {
		display: block;
		font-size: var(--text-sm);
		font-weight: 500;
		margin-bottom: .25rem;
		color: var(--text-2);
	}
	input {
		width: 100%;
		padding: .5rem .75rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		font-size: var(--text-base);
		box-sizing: border-box;
		background: var(--surface-2);
		color: var(--text-1);
	}
	input:focus {
		outline: none;
		border-color: var(--color-primary);
		box-shadow: 0 0 0 3px rgba(226, 61, 40, .15);
	}
	button {
		width: 100%;
		padding: .6rem;
		background: var(--color-primary);
		color: white;
		border: none;
		border-radius: 6px;
		font-size: var(--text-base);
		font-weight: 600;
		cursor: pointer;
		margin-top: .5rem;
	}
	button:hover:not(:disabled) { background: var(--color-primary-hover); }
	button:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}
	.btn-back {
		background: transparent;
		color: var(--text-2);
		font-weight: 400;
		font-size: var(--text-sm);
		margin-top: .25rem;
	}
	.btn-back:hover:not(:disabled) { background: var(--surface-2); }
	.btn-link {
		background: transparent;
		color: var(--text-2);
		font-weight: 400;
		font-size: var(--text-sm);
		margin-top: .5rem;
		text-decoration: underline;
	}
	.btn-link:hover:not(:disabled) { color: var(--text-1); }
	.info {
		background: var(--surface-2);
		color: var(--text-1);
		padding: .5rem .75rem;
		border-radius: 6px;
		font-size: var(--text-sm);
		margin-bottom: .5rem;
		line-height: 1.4;
	}
	.error {
		color: var(--color-primary);
		font-size: var(--text-sm);
		margin-bottom: .5rem;
	}
	.mfa-hint {
		font-size: var(--text-sm);
		color: var(--text-2);
		margin-bottom: 1rem;
		line-height: 1.4;
	}
	.org-hint {
		margin-top: 1.25rem;
		text-align: center;
		font-size: var(--text-xs);
		color: var(--text-muted);
	}
	.org-hint a {
		color: var(--text-2);
		text-decoration: underline;
	}
	.org-hint a:hover { color: var(--text-1); }
	.build-info {
		font-size: 0.6rem;
		color: var(--text-muted);
		text-align: center;
		margin-top: 1rem;
		opacity: 0.6;
	}
</style>
