<!--
  Die Hülle der Informationsseiten (/about, /pricing, /developers, /docs,
  /contact, /privacy).

  Der Rumpf kommt serverseitig gerendert aus demselben Markdown, das unter
  `/<seite>.md` ausgeliefert wird — deshalb `{@html}`: die Quelle ist
  `lib/server/agent/documents.ts`, also dieses Repository, keine Eingabe von
  außen. Serverseitig gerendert ist hier der Punkt der Übung: der Inhalt muss
  im ausgelieferten HTML stehen, nicht erst nach dem Start der App.
-->
<script lang="ts">
	import { page } from '$app/stores';
	import AppLogo from '$lib/components/AppLogo.svelte';
	import LegalFooter from '$lib/components/LegalFooter.svelte';
	import type { InfoPageData } from '$lib/agent/info';
	import { PAGES } from '$lib/agent/pages';

	let { data }: { data: InfoPageData } = $props();

	const nav = PAGES.filter((p) => p.path !== '/' && p.path !== '/status');
</script>

<svelte:head>
	<title>{data.title}</title>
	<meta name="description" content={data.description} />
	<link rel="canonical" href={data.canonical} />
	<link rel="alternate" type="text/markdown" href={data.markdownUrl} title="Markdown-Fassung dieser Seite" />
	<meta property="og:type" content="article" />
	<meta property="og:title" content={data.heading} />
	<meta property="og:description" content={data.description} />
	<meta property="og:url" content={data.canonical} />
	<meta property="og:site_name" content="ConvoyPlan" />
	<meta property="og:locale" content="de_DE" />
	<meta property="og:image" content="{$page.url.origin}/logo/light/LogoHorinzontal.png" />
	<meta name="twitter:card" content="summary_large_image" />
</svelte:head>

<div class="shell">
	<header>
		<a class="brand" href="/" aria-label="ConvoyPlan — Startseite">
			<AppLogo variant="horizontal" height={38} />
		</a>
		<nav aria-label="Informationsseiten">
			{#each nav as item (item.path)}
				<a href={item.path} aria-current={$page.url.pathname === item.path ? 'page' : undefined}>
					{item.title.replace(' — Marschplanung für Einsatzorganisationen', '')}
				</a>
			{/each}
		</nav>
	</header>

	<main>
		<h1>{data.heading}</h1>
		<!-- eslint-disable-next-line svelte/no-at-html-tags -->
		{@html data.html}

		<p class="md-hint">
			Maschinenlesbare Fassung dieser Seite:
			<a href={data.markdownUrl}>{data.markdownUrl}</a>
		</p>
	</main>

	<LegalFooter />
</div>

<style>
	.shell {
		max-width: 52rem;
		margin: 0 auto;
		padding: 1.5rem 1rem 4rem;
		color: var(--text-1, #e8edf2);
	}
	header {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 1rem 1.25rem;
		padding-bottom: 1rem;
		border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.1));
	}
	.brand { display: flex; align-items: center; }
	nav {
		display: flex;
		flex-wrap: wrap;
		gap: 0.25rem 1rem;
		font-size: var(--text-sm, 0.82rem);
	}
	nav a {
		color: var(--text-2, rgba(255, 255, 255, 0.55));
		text-decoration: none;
	}
	nav a:hover { color: var(--color-primary, #e23d28); }
	nav a[aria-current='page'] { color: var(--color-primary, #e23d28); font-weight: 600; }

	main { line-height: 1.65; font-size: var(--text-base, 0.92rem); }
	main :global(h2) {
		margin: 2rem 0 0.5rem;
		font-size: 1.25rem;
		padding-top: 0.75rem;
		border-top: 1px solid var(--border, rgba(255, 255, 255, 0.1));
	}
	main :global(h3) { margin: 1.5rem 0 0.4rem; font-size: 1.05rem; }
	main :global(p) { margin: 0 0 0.9rem; }
	main :global(ul) { margin: 0 0 1rem; padding-left: 1.2rem; }
	main :global(li) { margin-bottom: 0.3rem; }
	main :global(a) { color: var(--color-primary, #e23d28); }
	main :global(code) {
		background: var(--surface-2, #1e2d3d);
		padding: 0.1rem 0.3rem;
		border-radius: 4px;
		font-size: 0.9em;
	}
	main :global(pre) {
		background: var(--surface-2, #1e2d3d);
		padding: 0.75rem 1rem;
		border-radius: 6px;
		overflow-x: auto;
	}
	main :global(pre code) { background: none; padding: 0; }
	main :global(.table-wrap) { overflow-x: auto; margin: 0 0 1rem; }
	main :global(table) { border-collapse: collapse; width: 100%; font-size: var(--text-sm, 0.82rem); }
	main :global(th), main :global(td) {
		border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
		padding: 0.4rem 0.6rem;
		text-align: left;
		vertical-align: top;
	}
	main :global(th) { background: var(--surface-2, #1e2d3d); }
	main :global(hr) { border: none; border-top: 1px solid var(--border, rgba(255, 255, 255, 0.1)); margin: 2rem 0; }

	h1 { font-size: 1.7rem; margin: 1.5rem 0 1rem; }

	.md-hint {
		margin-top: 2.5rem;
		font-size: var(--text-sm, 0.82rem);
		color: var(--text-2, rgba(255, 255, 255, 0.55));
	}
	.md-hint a { color: inherit; }
</style>
