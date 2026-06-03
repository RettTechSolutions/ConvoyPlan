import { sveltekit } from '@sveltejs/kit/vite';
import { SvelteKitPWA } from '@vite-pwa/sveltekit';
import { defineConfig } from 'vite';
import { readFileSync } from 'fs';

const pkg = JSON.parse(readFileSync('package.json', 'utf-8'));
const gitSha = process.env.GIT_SHA?.slice(0, 7);
// APP_VERSION is injected at image build time from the git tag (see Dockerfile
// / release workflow); fall back to package.json for local dev builds.
const baseVersion = (process.env.APP_VERSION?.trim() || pkg.version).replace(/^v/, '');
// `git describe` already embeds the commit ("-g<sha>") for builds ahead of the
// last tag; only append the short sha when it isn't already part of the string,
// so the footer shows it exactly once.
const hasCommit = /[-+]g?[0-9a-f]{7,}/i.test(baseVersion);
const appVersion = gitSha && !hasCommit ? `${baseVersion}+${gitSha}` : baseVersion;

export default defineConfig({
	define: {
		__APP_VERSION__: JSON.stringify(appVersion),
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
