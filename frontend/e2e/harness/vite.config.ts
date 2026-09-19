import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const appHtml = fileURLToPath(new URL('../../src/app.html', import.meta.url));

/**
 * Die Farben und Schriftgrößen aus `src/app.html` in die Hülle spiegeln,
 * statt sie dort abzuschreiben: Ein Test, der Geometrie misst, misst sonst
 * gegen Werte, die längst auseinandergelaufen sind.
 */
function themenVariablen() {
	return {
		name: 'convoyplan-themen-variablen',
		transformIndexHtml(html: string) {
			const block = readFileSync(appHtml, 'utf-8').match(/<style>([\s\S]*?)<\/style>/);
			if (!block) throw new Error('src/app.html hat keinen <style>-Block mehr');
			return html.replace('</head>', `<style>${block[1]}</style></head>`);
		},
	};
}

/**
 * Hülle für Komponenten, die in der App hinter der Anmeldung sitzen.
 * `$lib/api` zeigt hier auf den Stub; alles andere kommt aus `src/lib`.
 */
export default defineConfig({
	root: fileURLToPath(new URL('.', import.meta.url)),
	plugins: [svelte({ configFile: false }), themenVariablen()],
	define: {
		// Ein Nightly-Stand, wie `git describe` ihn liefert — der längste Fall,
		// den die Fußzeile zeigen muss.
		__APP_VERSION__: JSON.stringify('2026.6.1-15-g951e75e'),
	},
	resolve: {
		alias: [
			{ find: /^\$lib\/api$/, replacement: fileURLToPath(new URL('./api-stub.ts', import.meta.url)) },
			{ find: /^\$lib\//, replacement: fileURLToPath(new URL('../../src/lib/', import.meta.url)) },
		],
	},
	server: { port: 4174, strictPort: true },
});
