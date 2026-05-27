<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth';
	import AppLogo from '$lib/components/AppLogo.svelte';

	let email = $state('');
	let password = $state('');
	let error = $state('');
	let loading = $state(false);

	// MFA step
	let mfaRequired = $state(false);
	let mfaToken = $state('');
	let mfaCode = $state('');

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

		{#if !mfaRequired}
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
</style>
