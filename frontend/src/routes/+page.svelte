<script lang="ts">
    import { goto } from '$app/navigation';
    import { orgAuthApi } from '$lib/api';
    import AppLogo from '$lib/components/AppLogo.svelte';

    let slugInput = $state('');
    let error = $state('');
    let loading = $state(false);

    async function handleSubmit() {
        const slug = slugInput.trim().toLowerCase();
        if (!slug) return;
        loading = true;
        error = '';
        try {
            await orgAuthApi.lookup(slug);
            goto(`/o/${slug}/login`);
        } catch {
            error = 'Organisation nicht gefunden. Bitte Code prüfen.';
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

        <form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
            <div class="field">
                <label for="slug">Organisations-Code</label>
                <input
                    id="slug"
                    type="text"
                    bind:value={slugInput}
                    placeholder="z.B. rettdienst-muenchen"
                    autocomplete="organization"
                    spellcheck="false"
                />
            </div>
            {#if error}
                <p class="error">{error}</p>
            {/if}
            <button type="submit" disabled={loading}>
                {loading ? 'Suche…' : 'Weiter →'}
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
    button:disabled { opacity: 0.6; cursor: not-allowed; }
    .error {
        color: var(--color-primary);
        font-size: var(--text-sm);
        margin-bottom: .5rem;
    }
</style>
