/**
 * Der gemeinsame `load` der Informationsseiten.
 *
 * HTML und Markdown entstehen aus derselben Quelle (`documents.ts`): die Seite
 * rendert dasselbe Dokument, das unter `/<name>.md` ausgeliefert wird. Damit
 * kann der `rel="alternate"`-Verweis auf den Markdown-Zwilling nicht auf etwas
 * anderes zeigen als das, was die Seite zeigt.
 */
import { error } from '@sveltejs/kit';
import * as docs from './documents';
import type { AgentContext } from './documents';
import { buildContext, discoveryEnabled } from './dispatch';
import { renderMarkdown } from './render';
import { pageFor } from '$lib/agent/pages';
import type { InfoPageData } from '$lib/agent/info';

type DocName = 'about' | 'contact' | 'privacy' | 'pricing' | 'developers' | 'docs';

const BUILDERS: Record<DocName, (ctx: AgentContext) => string> = {
	about: docs.aboutMd,
	contact: docs.contactMd,
	privacy: docs.privacyMd,
	pricing: docs.pricingMd,
	developers: docs.developersMd,
	docs: docs.docsMd
};

export async function loadInfoPage(
	name: DocName,
	url: URL,
	fetchFn: typeof fetch
): Promise<InfoPageData> {
	// Abgeschaltete Agenten-Auskunft heißt: diese Seiten gibt es nicht. Eine
	// rein interne Instanz soll keine Produktseiten ausliefern.
	if (!discoveryEnabled()) error(404, 'Nicht gefunden');

	const ctx = await buildContext(url, fetchFn);
	const rendered = renderMarkdown(BUILDERS[name](ctx));
	const entry = pageFor(`/${name}`);

	return {
		title: `${rendered.title} — ConvoyPlan`,
		heading: rendered.title,
		description: entry?.summary ?? rendered.lead,
		html: rendered.html,
		markdownUrl: `${ctx.base}/${name}.md`,
		canonical: `${ctx.base}/${name}`
	};
}
