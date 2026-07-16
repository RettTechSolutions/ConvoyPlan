<script lang="ts">
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import { onMount } from 'svelte';
    import { orgStore } from '$lib/stores/org';
    import { setActiveSlug } from '$lib/api/client';
    import { orgAuthApi } from '$lib/api';

    let { children } = $props();
    let ready = $state(false);

    onMount(async () => {
        const slug = ($page.params as Record<string, string>).slug;
        const isLoginPage = $page.url.pathname === `/o/${slug}/login`;

        // Login-Seite braucht keinen Token-Check
        if (isLoginPage) {
            setActiveSlug(slug);
            ready = true;
            return;
        }

        const token = orgStore.getToken(slug);
        if (!token) {
            goto(`/o/${slug}/login`);
            return;
        }

        // Token-Payload prüfen
        try {
            const payload = JSON.parse(atob(token.split('.')[1]));
            const exp = payload.exp * 1000;
            if (Date.now() > exp) {
                orgStore.removeToken(slug);
                goto(`/o/${slug}/login`);
                return;
            }
            if (payload.org_slug !== slug) {
                goto(`/o/${slug}/login`);
                return;
            }

            // Org-Name nachladen für den Store
            setActiveSlug(slug);
            let orgName = payload.org_slug; // Fallback
            try {
                const orgInfo = await orgAuthApi.lookup(slug);
                orgName = orgInfo.name;
            } catch { /* ignorieren */ }

            orgStore.setFromToken(slug, orgName, token);
            ready = true;
        } catch {
            goto(`/o/${slug}/login`);
        }
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
