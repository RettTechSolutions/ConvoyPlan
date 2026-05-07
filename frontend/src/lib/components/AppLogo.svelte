<script lang="ts">
  interface Props {
    variant?: 'horizontal' | 'main';
    height?: number | null;
    width?: number | null;
  }
  let { variant = 'horizontal', height = null, width = null }: Props = $props();

  const src = variant === 'main' ? '/Hauptlogo.svg' : '/LogoHorizontal.svg';

  // width takes precedence for horizontal logos; height for main/icon
  const style = width
    ? `width:${width}px;height:auto;display:block;object-fit:contain`
    : height
    ? `height:${height}px;width:auto;display:block;object-fit:contain`
    : `width:100%;height:auto;display:block;object-fit:contain`;
</script>

<img {src} alt="ConvoyPlan" {style} />
