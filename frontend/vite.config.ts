import { sveltekit } from '@sveltejs/kit/vite';
import { SvelteKitPWA } from '@vite-pwa/sveltekit';
import { defineConfig } from 'vite';

export default defineConfig({
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
				globPatterns: ['**/*.{js,css,html,svg,png,ico}'],
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
