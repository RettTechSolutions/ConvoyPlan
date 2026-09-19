import { test, expect } from '@playwright/test';
import { blockExternal } from './fixtures';

/**
 * Die Fußzeile der Planungs-Seitenleiste trägt Theme, Hilfe, Melden,
 * Installation und den Build-Stand. Zwei Zusagen, die man ihr nicht ansieht:
 *
 * 1. **Nichts wird gequetscht.** Vier Knöpfe und die Version passen nicht in
 *    eine 340px breite Zeile. Ohne Umbruch der *Zeile* brach stattdessen der
 *    Versionstext um: ein 45px schmaler, zweizeiliger Rest am rechten Rand,
 *    der nur noch wie ein Fehler aussah. Die Zusage ist deshalb, dass jeder
 *    Teil einzeilig bleibt und in der Leiste steht — nicht bloß, dass er
 *    irgendwie hineinpasst.
 * 2. **Der Build-Stand ist lesbar.** `git describe` liefert auf Nightly-Bauten
 *    "2026.6.1-15-g951e75e"; der Zähler ("-15-") sagt niemandem etwas.
 *
 * Die Hülle setzt genau diesen Nightly-Stand als `__APP_VERSION__`
 * (`e2e/harness/vite.config.ts`) — der längste Fall, den die Zeile zeigen muss.
 */

const HUELLE = 'http://localhost:4174';

test.describe('Fußzeile der Planungs-Seitenleiste', () => {
	test.beforeEach(async ({ page }) => {
		await blockExternal(page);
		await page.goto(`${HUELLE}/?k=fuss`);
		await expect(page.getByRole('button', { name: 'Fehler melden oder Funktion vorschlagen' })).toBeVisible();
	});

	test('stellt jeden Teil einzeilig in die Leiste', async ({ page }) => {
		const leiste = page.locator('.leiste');
		const fuss = page.locator('[data-tour="sidebar-footer"]');

		const rand = (await leiste.boundingBox())!;
		const teile = await fuss.locator(':scope > *').all();
		// Ohne diese Zusicherung wäre der Test auch dann grün, wenn die Fußzeile
		// gar nichts mehr zeigte.
		expect(teile.length).toBeGreaterThanOrEqual(5);

		for (const teil of teile) {
			const kasten = (await teil.boundingBox())!;
			const text = (await teil.innerText()).replace(/\s+/g, ' ').trim();

			expect(kasten.x, `"${text}" beginnt links der Leiste`).toBeGreaterThanOrEqual(rand.x - 0.5);
			expect(
				kasten.x + kasten.width,
				`"${text}" ragt rechts aus der Leiste`,
			).toBeLessThanOrEqual(rand.x + rand.width + 0.5);

			// Zeilen statt Höhe: `getClientRects()` über den Inhalt liefert ein
			// Rechteck je Inline-Kasten — unabhängig von Schriftgröße und
			// Polsterung. Zusammengefasst nach ihrer Oberkante ergeben sie die
			// Zeilen; die Toleranz fängt den Versatz zwischen Zeichen und
			// `<span>` in einem Knopf auf, der keiner ist.
			const zeilen = await teil.evaluate((el) => {
				const bereich = document.createRange();
				bereich.selectNodeContents(el);
				const kanten = [...bereich.getClientRects()].map((r) => r.top).sort((a, b) => a - b);
				return kanten.filter((kante, i) => i === 0 || kante - kanten[i - 1] > 4).length;
			});
			expect(zeilen, `"${text}" bricht auf ${zeilen} Zeilen um`).toBe(1);
		}

		// Und die Fußzeile selbst bleibt vollständig in der Leiste — sie hat
		// `overflow: hidden`, was darunter liegt, sähe niemand mehr.
		const kasten = (await fuss.boundingBox())!;
		expect(kasten.y + kasten.height).toBeLessThanOrEqual(rand.y + rand.height + 0.5);
	});

	test('zeigt den Build-Stand ohne den describe-Zähler', async ({ page }) => {
		const version = page.locator('[data-tour="sidebar-footer"] .app-version');

		await expect(version).toHaveText(/^v2026\.6\.1\s*·\s*951e75e\s*$/);
		// Der vollständige Stand bleibt erreichbar — man braucht ihn für eine
		// Fehlermeldung.
		await expect(version).toHaveAttribute('title', 'Build 2026.6.1-15-g951e75e');
	});
});
