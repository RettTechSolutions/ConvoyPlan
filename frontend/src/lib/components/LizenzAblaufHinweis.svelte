<script lang="ts" module>
    /** Ereignis, nach dem der Hinweis den Lizenzstatus neu lädt — das
     *  Admin-Portal löst es nach dem Eintragen oder Entfernen eines
     *  Schlüssels aus, damit der Hinweis nicht bis zum Neuladen stehen bleibt. */
    export const LIZENZ_GEAENDERT = 'convoyplan:lizenz-geaendert';
</script>

<script lang="ts">
    /**
     * Hinweis für Superadmins, dass der Lizenzschlüssel bald abläuft.
     *
     * Nach dem Ablauf fällt die Instanz in den Demo-Modus und niemand kann
     * mehr schreiben — mitten im Betrieb. Den Schlüssel erneuern kann nur der
     * Superadmin, deshalb sieht auch nur er diesen Hinweis; allen anderen
     * brächte er nichts als Unruhe. Ab wann gewarnt wird, entscheidet das
     * Backend (`expiry_warning`, backend/app/services/lizenz_ablauf.py) —
     * dieselbe Grenze wie die Mail an die Superadmins.
     *
     * Ist der Schlüssel schon abgelaufen, zeigt das Wurzel-Layout den
     * Demo-Banner; dieser Hinweis schweigt dann.
     */
    import { onDestroy, onMount } from 'svelte';
    import { licenseApi, type LicenseStatus } from '$lib/api';

    let status = $state<LicenseStatus | null>(null);

    async function laden() {
        try {
            // null: die Superadmin-Sitzung, auch unter /o/<slug>/.
            status = await licenseApi.getStatus(null);
        } catch {
            // Ein fehlender Hinweis ist besser als eine Fehlermeldung, die mit
            // der Arbeit auf dieser Seite nichts zu tun hat.
            status = null;
        }
    }

    onMount(() => {
        laden();
        window.addEventListener(LIZENZ_GEAENDERT, laden);
    });
    onDestroy(() => {
        if (typeof window !== 'undefined') window.removeEventListener(LIZENZ_GEAENDERT, laden);
    });

    function datum(iso: string): string {
        const [j, m, t] = iso.split('-');
        return t ? `${t}.${m}.${j}` : iso;
    }

    const text = $derived.by(() => {
        if (!status?.expiry_warning || status.expires_in_days === null || !status.expires) return null;
        const tage = status.expires_in_days;
        const wann = tage === 0 ? 'heute' : tage === 1 ? 'morgen' : `in ${tage} Tagen`;
        // Altschlüssel tragen einen Zeitstempel statt eines Datums.
        const bis = /^\d{4}-\d{2}-\d{2}$/.test(status.expires) ? ` (gültig bis ${datum(status.expires)})` : '';
        return {
            dringend: tage <= 7,
            text: `Der Lizenzschlüssel dieser Instanz läuft ${wann} ab${bis}. Danach ist sie im Demo-Modus und nur noch lesbar.`,
        };
    });
</script>

{#if text}
    <div class="lizenz-ablauf" class:dringend={text.dringend} role={text.dringend ? 'alert' : 'status'}>
        <span>{text.text}</span>
        <a href="/admin">Neuen Schlüssel eintragen →</a>
    </div>
{/if}

<style>
    /* Wie der Demo-Banner im Wurzel-Layout und OrgPlanHinweis: dieselbe
       Leiste, damit Hinweise zur Lizenz überall gleich aussehen. */
    .lizenz-ablauf {
        position: sticky;
        top: 0;
        z-index: 1000;
        padding: 0.5rem 1.25rem;
        display: flex;
        justify-content: center;
        align-items: center;
        flex-wrap: wrap;
        gap: 0.25rem 1.25rem;
        font-size: 0.875rem;
        font-weight: 500;
        text-align: center;
        color: #1c1917;
        background: #fde68a;
    }
    .lizenz-ablauf.dringend { background: #f59e0b; }
    .lizenz-ablauf a {
        color: inherit;
        text-decoration: underline;
        font-weight: 700;
        white-space: nowrap;
    }
</style>
