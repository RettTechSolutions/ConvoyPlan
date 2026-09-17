<!--
  Rechtliche Pflichtlinks (Impressum/Datenschutz) plus der Verweis auf die
  öffentliche Statusseite. Das Impressum des Herstellers wird zentral auf der
  Marketing-Website convoyplan.de gepflegt; die App verweist darauf.

  Beim Datenschutz ist die Herstellerseite das falsche Ziel: sie beschreibt,
  was convoyplan.de verarbeitet. Wer auf einer fremden Instanz steht, will
  wissen, was *diese* Instanz verarbeitet — und dass deren Betreiber der
  Verantwortliche im Sinne der DSGVO ist, nicht der Hersteller. Genau das
  steht unter `/privacy`. Die Seite gehört zur Agenten-Auskunft und existiert
  ohne sie nicht; dann bleibt nur der Verweis auf den Hersteller.

  `showStatus` blendet den Status-Link dort aus, wo er ins Leere zeigen würde —
  namentlich auf der Statusseite selbst.
-->
<script lang="ts">
	import { page } from '$app/stores';

	interface Props {
		showStatus?: boolean;
	}
	let { showStatus = true }: Props = $props();

	const eigeneDatenschutzseite = $derived($page.data.agentDiscovery === true);
</script>

<footer class="legal-footer">
	<a href="https://convoyplan.de/impressum" target="_blank" rel="noopener">Impressum</a>
	<span aria-hidden="true">·</span>
	{#if eigeneDatenschutzseite}
		<a href="/privacy">Datenschutz</a>
	{:else}
		<a href="https://convoyplan.de/datenschutz" target="_blank" rel="noopener">Datenschutz</a>
	{/if}
	{#if showStatus}
		<span aria-hidden="true">·</span>
		<a href="/status">Systemstatus</a>
	{/if}
</footer>

<style>
	.legal-footer {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.6rem;
		margin-top: 1.5rem;
		font-size: var(--text-sm, 0.8125rem);
		color: var(--text-muted, #888);
	}
	.legal-footer a {
		color: inherit;
		text-decoration: none;
		transition: color 0.15s;
	}
	.legal-footer a:hover {
		color: var(--text, #222);
		text-decoration: underline;
	}
	.legal-footer span {
		opacity: 0.6;
	}
</style>
