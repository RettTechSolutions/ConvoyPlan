import { execFileSync } from 'child_process';
import { sveltekit } from '@sveltejs/kit/vite';
import { SvelteKitPWA } from '@vite-pwa/sveltekit';
import { defineConfig } from 'vite';
import { readFileSync } from 'fs';

const pkg = JSON.parse(readFileSync('package.json', 'utf-8'));

const appVersion = (() => {
	try {
		return execFileSync('git', ['describe', '--tags', '--always', '--dirty'], { encoding: 'utf8' }).trim();
	} catch {
		return 'dev';
	}
})();

export default defineConfig({
	define: {
<<<<<<< HEAD
		__APP_VERSION__: JSON.stringify(appVersion),
=======
		__APP_VERSION__: JSON.stringify(pkg.version),
>>>>>>> 718168bf402caeec90cb4885e8ded2f2db1119a2
	},
	plugins: [
		sveltekit(),
		SvelteKitPWA({
			manifest: {
				name: 'ConvoyPlan',
				short_name: 'ConvoyPlan',
				description: 'Marschverbandsplanung für BOS',
				theme_color: '#1a2744',
				background_color: '#1a2744',
				display: 'standalone',
				icons: [
					{ src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
					{ src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
				],
			},
			workbox: {
				globPatterns: ['**/*.{js,css,html,svg,ico}'],
				globIgnores: ['logo/**', 'icons/**'],
				maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
				runtimeCaching: [
					{
						urlPattern: /^https:\/\/tile\.openstreetmap\.org\/.*/,
						handler: 'StaleWhileRevalidate',
						options: { cacheName: 'osm-tiles', expiration: { maxEntries: 500, maxAgeSeconds: 60 * 60 * 24 * 7 } },
					},
				],
			},
		}),
	],
});
