<script lang="ts">
    import { goto } from '$app/navigation';
    import { page } from '$app/state';
    import { onMount } from 'svelte';

    onMount(() => {
        goto(`/o/${(page.params as Record<string, string>).slug}/plan`, { replaceState: true });
    });
</script>
