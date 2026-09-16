/**
 * WebMCP: Werkzeuge, die ein Agent *im Browser* aufrufen kann.
 *
 * Der Vorschlag steht noch nicht in allen Browsern; `document.modelContext` ist
 * der Weg, `navigator.modelContext` der ältere Rückfall. Fehlt beides, passiert
 * hier nichts — die Funktion ist dann ein No-op und kostet nichts.
 *
 * Bewusst nur **lesende und navigierende** Werkzeuge. Ein Werkzeug, das im
 * angemeldeten Browser eines Disponenten eine Kolonne ändern könnte, gehört
 * nicht in eine Seite, die jede Erweiterung ansprechen kann; für Schreibzugriff
 * gibt es den MCP-Server mit ausdrücklicher Zustimmung und Audit-Log.
 */
import { PRODUCT, USE_WHEN, CAPABILITIES } from './facts';
import { PAGES } from './pages';

interface ToolResult {
	content: { type: 'text'; text: string }[];
}

interface ToolDescriptor {
	name: string;
	description: string;
	inputSchema: Record<string, unknown>;
	execute: (args: Record<string, unknown>) => Promise<ToolResult> | ToolResult;
}

interface ModelContext {
	registerTool?: (tool: ToolDescriptor) => unknown;
	provideContext?: (context: { tools: ToolDescriptor[] }) => unknown;
}

const asText = (value: unknown): ToolResult => ({
	content: [{ type: 'text', text: typeof value === 'string' ? value : JSON.stringify(value, null, 2) }]
});

function tools(): ToolDescriptor[] {
	return [
		{
			name: 'convoyplan_info',
			description:
				'Was ConvoyPlan ist, wofür diese Instanz gedacht ist und wann ein Agent sie aufrufen sollte. Liefert außerdem die Einstiegspfade für die maschinenlesbaren Beschreibungen.',
			inputSchema: { type: 'object', properties: {}, additionalProperties: false },
			execute: () =>
				asText({
					name: PRODUCT.name,
					tagline: PRODUCT.tagline,
					description: PRODUCT.description,
					instance: window.location.origin,
					useWhen: USE_WHEN,
					capabilities: CAPABILITIES.map((c) => ({ name: c.name, scope: c.scope })),
					machineReadable: {
						llmsTxt: '/llms.txt',
						agents: '/agents.md',
						auth: '/auth.md',
						openapi: '/openapi.json',
						agentCard: '/.well-known/agent-card.json'
					}
				})
		},
		{
			name: 'convoyplan_seiten',
			description:
				'Die öffentlichen Seiten dieser ConvoyPlan-Instanz mit Titel, Zweck und der Adresse der Markdown-Fassung.',
			inputSchema: { type: 'object', properties: {}, additionalProperties: false },
			execute: () =>
				asText(
					PAGES.map((p) => ({
						url: `${window.location.origin}${p.path}`,
						markdown: `${window.location.origin}${p.markdown}`,
						title: p.title,
						description: p.summary
					}))
				)
		},
		{
			name: 'convoyplan_instanz_status',
			description:
				'Der aktuelle Zustand dieser Instanz: Erreichbarkeit von Datenbank, Routingdienst und den externen Datenquellen. Ohne Anmeldung abrufbar.',
			inputSchema: { type: 'object', properties: {}, additionalProperties: false },
			execute: async () => {
				try {
					const resp = await fetch('/api/status/public', { headers: { accept: 'application/json' } });
					if (!resp.ok) return asText(`Status nicht abrufbar (HTTP ${resp.status}).`);
					return asText(await resp.json());
				} catch {
					return asText('Status nicht abrufbar — die Instanz antwortet gerade nicht.');
				}
			}
		},
		{
			name: 'convoyplan_organisation_pruefen',
			description:
				'Prüft, ob es auf dieser Instanz eine Organisation mit dem angegebenen Organisations-Code gibt, und liefert bei Erfolg den Pfad zu ihrer Anmeldemaske. Legt nichts an und meldet niemanden an.',
			inputSchema: {
				type: 'object',
				properties: {
					code: { type: 'string', description: 'Der Organisations-Code, z.B. "rdmu".' }
				},
				required: ['code'],
				additionalProperties: false
			},
			execute: async (args) => {
				const code = String(args.code ?? '')
					.trim()
					.toLowerCase();
				if (!code) return asText('Kein Organisations-Code angegeben.');
				try {
					const resp = await fetch(`/api/auth/org-lookup?slug=${encodeURIComponent(code)}`, {
						headers: { accept: 'application/json' }
					});
					if (!resp.ok) return asText({ code, exists: false });
					return asText({ code, exists: true, loginPath: `/o/${code}/login` });
				} catch {
					return asText('Die Instanz antwortet gerade nicht.');
				}
			}
		}
	];
}

export function registerWebMcpTools(): void {
	if (typeof window === 'undefined') return;
	const ctx: ModelContext | undefined =
		(document as unknown as { modelContext?: ModelContext }).modelContext ??
		(navigator as unknown as { modelContext?: ModelContext }).modelContext;
	if (!ctx) return;
	try {
		if (typeof ctx.registerTool === 'function') {
			for (const tool of tools()) ctx.registerTool(tool);
		} else if (typeof ctx.provideContext === 'function') {
			ctx.provideContext({ tools: tools() });
		}
	} catch {
		// Ein Browser, der das Modell anders schneidet, darf die Seite nicht
		// mitnehmen — die Werkzeuge sind eine Zugabe, keine Voraussetzung.
	}
}
