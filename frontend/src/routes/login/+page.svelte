<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth';

	let email = $state('');
	let password = $state('');
	let error = $state('');
	let loading = $state(false);

	async function handleLogin(e: Event) {
		e.preventDefault();
		loading = true;
		error = '';
		try {
			await auth.login(email, password);
			goto('/plan');
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Login fehlgeschlagen';
		} finally {
			loading = false;
		}
	}
</script>

<div class="login-container">
	<div class="login-card">
		<h1>MarschPlan</h1>
		<p class="subtitle">Marschverbandsplanung für BOS</p>

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
	</div>
</div>

<style>
	.login-container {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 100vh;
		background: #1a2744;
	}
	.login-card {
		background: white;
		border-radius: 8px;
		padding: 2.5rem;
		width: 100%;
		max-width: 380px;
		box-shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
	}
	h1 {
		margin: 0 0 0.25rem;
		font-size: 1.8rem;
		color: #1a2744;
	}
	.subtitle {
		color: #666;
		margin: 0 0 1.5rem;
		font-size: 0.9rem;
	}
	.field {
		margin-bottom: 1rem;
	}
	label {
		display: block;
		font-size: 0.85rem;
		font-weight: 600;
		margin-bottom: 0.3rem;
		color: #333;
	}
	input {
		width: 100%;
		padding: 0.6rem 0.75rem;
		border: 1px solid #ccc;
		border-radius: 4px;
		font-size: 1rem;
		box-sizing: border-box;
	}
	input:focus {
		outline: none;
		border-color: #1a2744;
	}
	button {
		width: 100%;
		padding: 0.75rem;
		background: #1a2744;
		color: white;
		border: none;
		border-radius: 4px;
		font-size: 1rem;
		font-weight: 600;
		cursor: pointer;
		margin-top: 0.5rem;
	}
	button:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}
	.error {
		color: #c0392b;
		font-size: 0.875rem;
		margin-bottom: 0.5rem;
	}
</style>
