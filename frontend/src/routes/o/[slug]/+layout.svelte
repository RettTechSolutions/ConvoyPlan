<script lang="ts">
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import { onMount, onDestroy } from 'svelte';
    import { orgStore } from '$lib/stores/org';
    import { setOrgBranding, clearOrgBranding } from '$lib/stores/branding';

    let { children } = $props();
    let ready = $state(false);

    // Org-Branding gilt nur innerhalb dieses Layouts (öffentlicher Endpoint,
    // damit auch die Login-Seite bereits im Org-Look erscheint). Nicht blockierend.
    async function loadOrgBranding(slug: string) {
        try {
            const resp = await fetch(`/api/branding/org/${encodeURIComponent(slug)}`);
            if (resp.ok) {
                setOrgBranding(await resp.json());
            }
        } catch {
            // Plattform-Branding behalten
        }
    }

    onDestroy(() => {
        // Beim Verlassen des Org-Bereichs wieder das Plattform-Branding anwenden.
        clearOrgBranding();
    });

    onMount(async () => {
        const slug = ($page.params as Record<string, string>).slug;
        const isLoginPage = $page.url.pathname === `/o/${slug}/login`;

        loadOrgBranding(slug);

        // Login-Seite braucht keinen Token-Check
        if (isLoginPage) {
            ready = true;
            return;
        }

        // Die Sitzung steckt im HttpOnly-Cookie — ob sie gilt, weiß nur der
        // Server. Ablauf, Organisation und Mitgliedschaft prüft er in einem
        // Zug; das frühere Dekodieren des Tokens im Browser prüfte nur, was
        // beim Anmelden galt.
        const ctx = await orgStore.load(slug);
        if (!ctx) {
            goto(`/o/${slug}/login`);
            return;
        }
        ready = true;
    });
</script>

<svelte:head>
    <!-- Tab-Titel = Organisationsname, damit User sofort sehen, in welchem Portal sie sind.
         Solange der Name noch nicht geladen ist, greift der Titel aus dem Root-Layout. -->
    {#if $orgStore?.org_name}
        <title>{$orgStore.org_name}</title>
    {/if}
</svelte:head>

{#if ready}
    {@render children()}
{/if}
