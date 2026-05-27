<script lang="ts">
    import { goto } from '$app/navigation';
    import { orgAuthApi } from '$lib/api';

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

<div class="root-page">
    <div class="card">
        <h1>ConvoyPlan</h1>
        <p class="subtitle">Bitte Organisations-Code eingeben</p>
        <form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
            <input
                type="text"
                bind:value={slugInput}
                placeholder="z.B. rettdienst-muenchen"
                autocomplete="organization"
                spellcheck="false"
            />
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
    .root-page {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 100vh;
        background: var(--color-bg, #f5f5f5);
    }
    .card {
        background: var(--color-surface, #fff);
        border-radius: 12px;
        padding: 2.5rem;
        width: 100%;
        max-width: 380px;
        box-shadow: 0 4px 24px rgba(0,0,0,0.08);
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }
    h1 { margin: 0; font-size: 1.6rem; }
    .subtitle { color: var(--color-text-muted, #666); margin: 0; }
    input {
        width: 100%;
        padding: 0.75rem 1rem;
        border: 1px solid var(--color-border, #ddd);
        border-radius: 8px;
        font-size: 1rem;
        box-sizing: border-box;
    }
    button {
        width: 100%;
        padding: 0.75rem;
        background: var(--color-primary, #2563eb);
        color: #fff;
        border: none;
        border-radius: 8px;
        font-size: 1rem;
        cursor: pointer;
    }
    button:disabled { opacity: 0.6; cursor: not-allowed; }
    .error { color: #dc2626; font-size: 0.9rem; margin: 0; }
</style>
