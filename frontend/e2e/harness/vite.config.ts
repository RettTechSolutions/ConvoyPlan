import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';

/**
 * Hülle für Komponenten, die in der App hinter der Anmeldung sitzen.
 * `$lib/api` zeigt hier auf den Stub; alles andere kommt aus `src/lib`.
 */
export default defineConfig({
	root: fileURLToPath(new URL('.', import.meta.url)),
	plugins: [svelte({ configFile: false })],
	resolve: {
		alias: [
			{ find: /^\$lib\/api$/, replacement: fileURLToPath(new URL('./api-stub.ts', import.meta.url)) },
			{ find: /^\$lib\//, replacement: fileURLToPath(new URL('../../src/lib/', import.meta.url)) },
		],
	},
	server: { port: 4174, strictPort: true },
});
