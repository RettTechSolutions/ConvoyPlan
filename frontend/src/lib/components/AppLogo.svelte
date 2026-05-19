<script lang="ts">
    import { brandingStore } from '$lib/stores/branding';
    import { themeStore } from '$lib/stores/theme';

    interface Props {
        variant?: 'horizontal' | 'main';
        height?: number | null;
        width?: number | null;
    }
    let { variant = 'horizontal', height = null, width = null }: Props = $props();

    // Dark theme (dunkle Seite) → Light-Set-Logos (helle Logos auf dunklem Hintergrund)
    // Light theme (helle Seite)  → Dark-Set-Logos  (dunkle Logos auf hellem Hintergrund)
    const src = $derived(
        variant === 'main'
            ? ($brandingStore.logo_main_url
                ?? ($themeStore === 'light' ? '/logo/dark/LogoVertical.png' : '/logo/light/LogoVertical.png'))
            : ($brandingStore.logo_horizontal_url
                ?? ($themeStore === 'light' ? '/logo/dark/LogoHorinzontal.png' : '/logo/light/LogoHorinzontal.png'))
    );

    const style = width
        ? `width:${width}px;height:auto;display:block;object-fit:contain`
        : height
        ? `height:${height}px;width:auto;display:block;object-fit:contain`
        : `width:100%;height:auto;display:block;object-fit:contain`;
</script>

<img {src} alt={$brandingStore.app_name} {style} />
