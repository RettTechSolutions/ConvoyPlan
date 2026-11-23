import { test, expect } from '@playwright/test';
import { readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

// Bis 2026-11 lagen unter `static/icons` und `static/logo` 22,6 MB: `icon-192.png` war ein
// Bild mit 1616 × 1616 px und 2,5 MB, byte-gleich mit `icon-512.png`, und das Favicon hatte
// 3,8 MB. Jeder Browser, der das Tab-Icon oder das Logo der Anmeldeseite holte, lud das mit,
// auch der Fahrer-Link über Mobilfunk. Die Dateinamen sind geblieben, weil Manifeste,
// `og:image` und die Agenten-Auskunft auf sie zeigen.

/** Breite und Höhe aus dem IHDR-Block eines PNG. */
function pngMasse(b: Buffer): [number, number] {
	expect(b.subarray(1, 4).toString('latin1')).toBe('PNG');
	return [b.readUInt32BE(16), b.readUInt32BE(20)];
}

for (const manifest of ['app.webmanifest', 'tracking.webmanifest']) {
	test(`${manifest}: jedes Icon hat die Größe, die das Manifest angibt`, async ({ request }) => {
		const { icons } = await (await request.get(`/${manifest}`)).json();
		expect(icons.length).toBeGreaterThan(0);
		for (const icon of icons as { src: string; sizes: string }[]) {
			const antwort = await request.get(icon.src);
			expect(antwort.ok(), icon.src).toBe(true);
			const [b, h] = pngMasse(await antwort.body());
			expect(`${b}x${h}`, icon.src).toBe(icon.sizes);
		}
	});
}

test('kein Bild unter static/icons und static/logo wiegt mehr als 100 KB', () => {
	const zuGross: string[] = [];
	const durch = (verzeichnis: string) => {
		for (const name of readdirSync(verzeichnis)) {
			const pfad = join(verzeichnis, name);
			const info = statSync(pfad);
			if (info.isDirectory()) durch(pfad);
			else if (info.size > 100_000) zuGross.push(`${pfad} (${Math.round(info.size / 1000)} KB)`);
		}
	};
	durch('static/icons');
	durch('static/logo');
	expect(zuGross).toEqual([]);
});
