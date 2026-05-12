<script lang="ts">
    import { brandingStore } from '$lib/stores/branding';

    interface Props {
        variant?: 'horizontal' | 'main';
        height?: number | null;
        width?: number | null;
    }
    let { variant = 'horizontal', height = null, width = null }: Props = $props();

    const fallbackSrc = variant === 'main' ? '/Hauptlogo.svg' : '/LogoHorizontal.svg';

    const src = $derived(
        variant === 'main'
            ? ($brandingStore.logo_main_url ?? fallbackSrc)
            : ($brandingStore.logo_horizontal_url ?? fallbackSrc)
    );

    const style = width
        ? `width:${width}px;height:auto;display:block;object-fit:contain`
        : height
        ? `height:${height}px;width:auto;display:block;object-fit:contain`
        : `width:100%;height:auto;display:block;object-fit:contain`;
</script>

<img {src} alt={$brandingStore.app_name} {style} />
