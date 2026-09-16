<script lang="ts">
    /**
     * Editor für eine E-Mail-Vorlage — Betreff, HTML, Vorschau, Testversand.
     *
     * Eigene Komponente, weil es seit der Nachfrage-Mail zwei Vorlagen an zwei
     * Stellen des Admin-Portals gibt (Branding und Demo) und ein zweites Mal
     * dieselben achtzig Zeilen Markup zwei Stellen zum Auseinanderlaufen
     * geschaffen hätte.
     */
    import { onMount } from 'svelte';
    import { auth } from '$lib/stores/auth';
    import { emailTemplateApi, type EmailTemplate, type EmailTemplateKind } from '$lib/api';
    import { authHeaders } from '$lib/api/client';

    let { kind, title }: { kind: EmailTemplateKind; title: string } = $props();

    let template = $state<EmailTemplate | null>(null);
    let form = $state({ subject: '', html: '' });
    let saving = $state(false);
    let resetting = $state(false);
    let testing = $state(false);
    let error = $state('');
    let success = $state('');
    let varsOpen = $state(false);

    /** Was ein Platzhalter bedeutet. Welche es gibt, sagt das Backend — diese
     *  Tabelle erklärt sie nur; ein unbekannter Name bleibt ohne Erklärung
     *  stehen, statt die Liste zu verschweigen. */
    const MEANINGS: Record<string, string> = {
        recipient_name: 'Name des Empfängers (leer, wenn keiner angegeben wurde)',
        recipient_name_greeting: 'Name mit führendem Leerzeichen — für „Hallo{recipient_name_greeting},"',
        email: 'E-Mail-Adresse des Empfängers',
        password: 'Generiertes Passwort',
        login_url: 'Anmeldelink der Organisation',
        app_name: 'App-Name (aus dem Branding)',
        logo_block: 'Logo-Block (automatisch aus dem Branding)',
        color_primary: 'Primärfarbe (aus dem Branding)',
        color_primary_hover: 'Primärfarbe für Hover-Zustände',
        contact_url: 'Ziel der Schaltfläche „Gemeinsame Session vereinbaren"',
        unsubscribe_url: 'Abmeldelink für diesen Empfänger',
    };

    function flash(message: string) {
        success = message;
        setTimeout(() => { success = ''; }, 4000);
    }

    function fail(e: unknown, fallback: string) {
        error = e instanceof Error ? e.message : fallback;
    }

    async function load() {
        try {
            template = await emailTemplateApi.get(kind);
            form = { subject: template.subject, html: template.html };
        } catch {
            /* Kein Superadmin oder Backend nicht erreichbar — der Abschnitt
               bleibt dann leer statt eine Fehlermeldung zu zeigen, die beim
               Laden der Seite niemand einordnen kann. */
        }
    }

    onMount(load);

    async function save() {
        saving = true;
        error = '';
        success = '';
        try {
            template = await emailTemplateApi.update(kind, form);
            form = { subject: template.subject, html: template.html };
            flash('Vorlage gespeichert.');
        } catch (e) {
            fail(e, 'Fehler beim Speichern');
        } finally {
            saving = false;
        }
    }

    async function reset() {
        if (!confirm('Vorlage wirklich auf den Standard zurücksetzen? Alle Anpassungen gehen verloren.')) return;
        resetting = true;
        error = '';
        success = '';
        try {
            template = await emailTemplateApi.reset(kind);
            form = { subject: template.subject, html: template.html };
            flash('Vorlage auf den Standard zurückgesetzt.');
        } catch (e) {
            fail(e, 'Fehler beim Zurücksetzen');
        } finally {
            resetting = false;
        }
    }

    async function sendTest() {
        testing = true;
        error = '';
        success = '';
        try {
            const result = await emailTemplateApi.sendTest(kind);
            flash(`Testmail an ${result.recipient} verschickt.`);
        } catch (e) {
            fail(e, 'Testversand fehlgeschlagen');
        } finally {
            testing = false;
        }
    }

    async function preview() {
        error = '';
        try {
            // Als Blob statt als einfacher Link: Die Vorschau hängt an der
            // Superadmin-Sitzung, und der Aufruf trägt den CSRF-Kopf, den ein
            // <a target="_blank"> nicht setzen kann.
            const resp = await fetch(emailTemplateApi.previewUrl(kind), {
                credentials: 'same-origin',
                headers: authHeaders(),
            });
            if (!resp.ok) throw new Error(resp.statusText);
            const url = URL.createObjectURL(await resp.blob());
            window.open(url, '_blank', 'noopener');
            // Freigeben, sobald der neue Tab Zeit zum Laden hatte.
            setTimeout(() => URL.revokeObjectURL(url), 60_000);
        } catch (e) {
            fail(e, 'Vorschau fehlgeschlagen');
        }
    }
</script>

<div class="section branding-panel">
    <div class="section-header sh-inline">
        <strong>{title}</strong>
        {#if template}
            {#if template.is_custom}
                <span class="badge et-badge-custom">Angepasst</span>
            {:else}
                <span class="badge et-badge-default">Standard</span>
            {/if}
        {/if}
    </div>

    {#if error}
        <div class="error-bar">{error} <button onclick={() => error = ''}>✕</button></div>
    {/if}
    {#if success}
        <div class="success-bar">{success}</div>
    {/if}

    {#if template}
        <p class="hint" style="margin:-.25rem 0 1rem">{template.description}</p>

        <div class="bf-section">
            <label class="bf-label">Betreff
                <input type="text" bind:value={form.subject} spellcheck="false" />
            </label>
        </div>

        <div class="bf-section">
            <label class="bf-label">HTML-Vorlage
                <textarea
                    bind:value={form.html}
                    class="et-textarea"
                    spellcheck="false"
                    placeholder="<!DOCTYPE html>..."
                ></textarea>
            </label>
        </div>

        <div class="et-vars-panel">
            <button class="et-vars-toggle" onclick={() => varsOpen = !varsOpen}>
                {varsOpen ? '▾' : '▸'} Verfügbare Variablen ({template.placeholders.length})
            </button>
            {#if varsOpen}
                <table class="et-vars-table">
                    <thead>
                        <tr><th>Variable</th><th>Bedeutung</th></tr>
                    </thead>
                    <tbody>
                        {#each template.placeholders as name}
                            <tr>
                                <td><code>{`{${name}}`}</code></td>
                                <td>{MEANINGS[name] ?? '—'}</td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
                <p class="hint" style="margin:.5rem 0 0; font-size:var(--text-xs)">
                    Alles andere in geschweiften Klammern bleibt unverändert stehen —
                    ein Tippfehler im Namen verschluckt den Text also nicht, er landet
                    wörtlich in der Mail.
                </p>
            {/if}
        </div>

        <div class="bf-actions" style="margin-top:1rem">
            <button class="btn-secondary" onclick={preview}>Vorschau</button>
            <button class="btn-secondary" onclick={sendTest} disabled={testing}>
                {testing ? 'Wird verschickt…' : 'Testmail an mich'}
            </button>
            <button
                class="btn-secondary"
                onclick={reset}
                disabled={resetting || !template.is_custom}
            >
                {resetting ? '…' : 'Auf Standard zurücksetzen'}
            </button>
            <button class="btn-primary" onclick={save} disabled={saving}>
                {saving ? 'Wird gespeichert…' : 'Speichern'}
            </button>
        </div>
    {:else}
        <p class="hint">Vorlage nicht verfügbar</p>
    {/if}
</div>

<style>
    /* Bewusst eine Kopie der Regeln aus dem Admin-Portal statt globaler Klassen:
       Svelte kapselt Stile je Komponente, und die Alternative wäre, ein Dutzend
       Regeln global zu machen, die sonst nirgends gebraucht werden. */
    .section {
        background: var(--surface-1);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1rem;
        box-shadow: var(--shadow);
        overflow-x: auto;
    }
    .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: .75rem;
        font-size: var(--text-sm);
        font-weight: 500;
        color: var(--text-1);
    }
    .section-header.sh-inline { justify-content: flex-start; gap: .75rem; }
    .hint { color: var(--text-muted); font-size: var(--text-sm); }
    .badge { display: inline-block; padding: .15rem .5rem; border-radius: 3px; font-size: var(--text-xs); font-weight: 600; }
    .et-badge-custom { background: rgba(210,120,30,.2); color: #e8a050; border: 1px solid rgba(210,120,30,.4); }
    .et-badge-default { background: var(--surface-2); color: var(--text-muted); border: 1px solid var(--border); }
    .error-bar {
        background: var(--color-primary-hover);
        color: white;
        padding: .4rem .75rem;
        border-radius: 4px;
        margin-bottom: 1rem;
        display: flex;
        justify-content: space-between;
    }
    .error-bar button { background: none; border: none; color: white; cursor: pointer; }
    .success-bar {
        background: rgba(107,127,77,.15);
        border: 1px solid rgba(107,127,77,.4);
        color: #a8c070;
        padding: .4rem .75rem;
        border-radius: 4px;
        margin-bottom: 1rem;
        font-size: var(--text-sm);
    }
    .bf-section { margin-bottom: 1.5rem; }
    .bf-label { display: flex; flex-direction: column; gap: .25rem; font-size: var(--text-sm); color: var(--text-2); }
    .bf-label input[type="text"] {
        padding: .5rem .75rem;
        border: 1px solid var(--border);
        border-radius: 6px;
        font-size: var(--text-base);
        width: 100%;
        max-width: var(--admin-field, 34rem);
        box-sizing: border-box;
        background: var(--surface-2);
        color: var(--text-1);
    }
    .bf-label input[type="text"]:focus { outline: none; border-color: var(--color-primary); }
    .bf-actions { display: flex; gap: .5rem; flex-wrap: wrap; }
    .btn-primary {
        padding: .5rem 1rem;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 6px;
        font-weight: 600;
        cursor: pointer;
        font-size: var(--text-sm);
    }
    .btn-primary:disabled { opacity: .6; cursor: not-allowed; }
    .btn-secondary {
        padding: .5rem 1rem;
        background: transparent;
        color: var(--text-2);
        border: 1px solid var(--border);
        border-radius: 6px;
        font-weight: 600;
        cursor: pointer;
        font-size: var(--text-sm);
    }
    .btn-secondary:hover { background: var(--surface-2); }
    .btn-secondary:disabled { opacity: .5; cursor: not-allowed; }
    .et-textarea {
        width: 100%;
        height: 400px;
        resize: vertical;
        font-family: 'Menlo', 'Consolas', 'Monaco', monospace;
        font-size: 12px;
        line-height: 1.5;
        padding: .5rem .75rem;
        border: 1px solid var(--border);
        border-radius: 6px;
        background: var(--surface-2);
        color: var(--text-1);
        box-sizing: border-box;
    }
    .et-textarea:focus { outline: none; border-color: var(--color-primary); }
    .et-vars-panel { margin-bottom: .75rem; }
    .et-vars-toggle {
        background: none;
        border: none;
        cursor: pointer;
        font-size: var(--text-sm);
        color: var(--color-primary);
        padding: 0;
        font-weight: 500;
    }
    .et-vars-table { width: 100%; border-collapse: collapse; font-size: var(--text-xs); margin-top: .5rem; }
    .et-vars-table th {
        text-align: left;
        padding: .3rem .5rem;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: .04em;
        border-bottom: 1px solid var(--border);
    }
    .et-vars-table td { padding: .3rem .5rem; border-bottom: 1px solid var(--border); color: var(--text-2); vertical-align: middle; }
    .et-vars-table tr:last-child td { border-bottom: none; }

    @media (max-width: 720px) {
        .et-textarea { height: 240px; font-size: 13px; }
    }
</style>
