<!--
  Rechtliche Pflichtlinks (Impressum/Datenschutz).
  Die Rechtsseiten werden zentral auf der Marketing-Website convoyplan.de
  gepflegt; die App verweist darauf.
-->
<footer class="legal-footer">
	<a href="https://convoyplan.de/impressum" target="_blank" rel="noopener">Impressum</a>
	<span aria-hidden="true">·</span>
	<a href="https://convoyplan.de/datenschutz" target="_blank" rel="noopener">Datenschutz</a>
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
