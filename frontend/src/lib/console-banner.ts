/**
 * Konsolen-Startbanner — ASCII-Art plus Debug-Infos beim App-Start.
 * Wird einmalig aus dem Root-Layout (onMount, nur Browser) aufgerufen.
 */

const ASCII_ART = String.raw`
  ____                                ____  _
 / ___|___  _ ____   _____  _   _    |  _ \| | __ _ _ __
| |   / _ \| '_ \ \ / / _ \| | | |   | |_) | |/ _' | '_ \
| |__| (_) | | | \ V / (_) | |_| |   |  __/| | (_| | | | |
 \____\___/|_| |_|\_/ \___/ \__, |   |_|   |_|\__,_|_| |_|
                            |___/
       ____    ____    ____    ____
      |o o |==|o o |==|o o |==|LEAD|=>
      'O--O'  'O--O'  'O--O'  'O--O'
`;

let printed = false;

export function printConsoleBanner(): void {
	if (printed || typeof window === 'undefined') return;
	printed = true;

	console.log(
		'%c' + ASCII_ART,
		'color:#E23D28; font-family:ui-monospace,monospace; line-height:1.2;'
	);
	console.log(
		'%cConvoyPlan%c v' + __APP_VERSION__ + ' — Konvoi-Planung für BOS & Hilfsorganisationen',
		'color:#E23D28; font-weight:bold; font-size:1.1em;',
		'color:inherit;'
	);

	console.groupCollapsed('%c🔧 Debug-Infos', 'color:#3498db; font-weight:bold;');
	console.log('Version        :', __APP_VERSION__);
	console.log('Build-Modus    :', import.meta.env.MODE);
	console.log('URL            :', window.location.origin);
	console.log('User-Agent     :', navigator.userAgent);
	console.log('Sprache        :', navigator.language);
	console.log('Zeitzone       :', Intl.DateTimeFormat().resolvedOptions().timeZone);
	console.log('Viewport       :', `${window.innerWidth}×${window.innerHeight} @ ${window.devicePixelRatio}x`);
	console.log('Online         :', navigator.onLine);
	console.log('PWA-Modus      :', window.matchMedia('(display-mode: standalone)').matches ? 'standalone (installiert)' : 'Browser-Tab');
	console.log('Service Worker :', 'serviceWorker' in navigator ? 'unterstützt' : 'nicht unterstützt');
	console.log('Touch          :', navigator.maxTouchPoints > 0 ? `ja (${navigator.maxTouchPoints} Punkte)` : 'nein');
	if ('memory' in performance) {
		// Chrome-only, nicht standardisiert
		const mem = (performance as Performance & { memory: { usedJSHeapSize: number; jsHeapSizeLimit: number } }).memory;
		console.log('JS-Heap        :', `${(mem.usedJSHeapSize / 1048576).toFixed(1)} MB / ${(mem.jsHeapSizeLimit / 1048576).toFixed(0)} MB`);
	}
	console.groupEnd();

	// ── Easter Egg: Dankeschön ──────────────────────────────────────────
	// Kleines verstecktes Dankeschön für die Tester & Unterstützer, das nur
	// neugierige Webentwickler in der Konsole finden.
	console.log(
		'\n%c☕ %cDanke, David!%c\nFür dein ausführliches Feedback, dein Auge fürs Detail\nund die Unterstützung beim Feinschliff von ConvoyPlan.\n%c— made with ❤ by the ConvoyPlan-Team',
		'font-size:1.2em;',
		'color:#E23D28; font-weight:bold; font-size:1.1em;',
		'color:inherit;',
		'color:#888; font-style:italic;'
	);

	// Backend-Infos asynchron nachreichen, sobald verfügbar (non-blocking)
	fetch('/api/version')
		.then((r) => (r.ok ? r.json() : null))
		.then((v: { version?: string; sha?: string; latest?: string; update_available?: boolean } | null) => {
			if (!v) return;
			console.groupCollapsed('%c🖥 Backend', 'color:#3498db; font-weight:bold;');
			console.log('Version  :', v.version ?? 'unbekannt');
			console.log('Commit   :', v.sha ?? 'unbekannt');
			if (v.update_available) {
				console.log(
					'%cUpdate verfügbar: ' + v.latest + ' → https://github.com/RettTechSolutions/ConvoyPlan/releases/latest',
					'color:#f59e0b; font-weight:bold;'
				);
			}
			console.groupEnd();
		})
		.catch(() => {
			console.warn('Backend nicht erreichbar — /api/version lieferte keine Antwort.');
		});
}
