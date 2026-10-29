<script lang="ts">
	/**
	 * Schnee, Fledermäuse, Konfetti und Feuerwerk auf einer Leinwand über der
	 * Seite. `pointer-events: none` — durch sie hindurch bleibt alles bedienbar.
	 *
	 * Wird per `import()` aus `SaisonRahmen.svelte` nachgeladen und kostet ohne
	 * eingeschaltete Saison nichts. Bei `prefers-reduced-motion` wird sie gar
	 * nicht erst eingehängt.
	 */
	import { onMount } from 'svelte';
	import type { Partikel } from './kalender';

	let { art }: { art: Exclude<Partikel, null> } = $props();

	let leinwand: HTMLCanvasElement;

	type Teil = {
		x: number; y: number; vx: number; vy: number;
		r: number; dreh: number; vdreh: number; farbe: string; leben: number; phase: number;
	};

	const KONFETTI = ['#ef4444', '#f59e0b', '#10b981', '#3b82f6', '#a855f7', '#ec4899'];
	const FEUER = ['#fde047', '#f97316', '#ef4444', '#a855f7', '#38bdf8', '#4ade80'];

	onMount(() => {
		const ctx = leinwand.getContext('2d');
		if (!ctx) return;
		let breite = 0;
		let hoehe = 0;
		let teile: Teil[] = [];
		let bisZumNaechsten = 0;
		let zuletzt = performance.now();
		let laeuft = true;
		let rahmen = 0;

		const zufall = (a: number, b: number) => a + Math.random() * (b - a);

		function groesse() {
			const dpr = Math.min(window.devicePixelRatio || 1, 2);
			breite = window.innerWidth;
			hoehe = window.innerHeight;
			leinwand.width = breite * dpr;
			leinwand.height = hoehe * dpr;
			ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
		}

		/** Dichte nach Fläche, gedeckelt — am Telefon weniger als am Schreibtisch. */
		const anzahl = (je: number, max: number) => Math.min(max, Math.round((breite * hoehe) / je));

		function flocke(oben = false): Teil {
			return {
				x: zufall(0, breite), y: oben ? zufall(-hoehe, 0) : zufall(0, hoehe),
				vx: zufall(-10, 10), vy: zufall(15, 45), r: zufall(1, 3.2),
				dreh: 0, vdreh: 0, farbe: '', leben: 1, phase: zufall(0, Math.PI * 2),
			};
		}

		function schnipsel(oben = false): Teil {
			return {
				x: zufall(0, breite), y: oben ? zufall(-hoehe, 0) : zufall(0, hoehe),
				vx: zufall(-15, 15), vy: zufall(30, 70), r: zufall(3, 6),
				dreh: zufall(0, Math.PI), vdreh: zufall(-4, 4),
				farbe: KONFETTI[Math.floor(Math.random() * KONFETTI.length)], leben: 1, phase: 0,
			};
		}

		function fledermaus(): Teil {
			const vonLinks = Math.random() < 0.5;
			return {
				x: vonLinks ? -30 : breite + 30, y: zufall(hoehe * 0.08, hoehe * 0.6),
				vx: (vonLinks ? 1 : -1) * zufall(90, 160), vy: 0, r: zufall(16, 26),
				dreh: 0, vdreh: 0, farbe: '', leben: 1, phase: zufall(0, Math.PI * 2),
			};
		}

		function rakete() {
			const x = zufall(breite * 0.1, breite * 0.9);
			const y = zufall(hoehe * 0.1, hoehe * 0.45);
			const farbe = FEUER[Math.floor(Math.random() * FEUER.length)];
			for (let i = 0; i < 42; i++) {
				const w = (i / 42) * Math.PI * 2;
				const v = zufall(60, 150);
				teile.push({ x, y, vx: Math.cos(w) * v, vy: Math.sin(w) * v, r: 2.6, dreh: 0, vdreh: 0, farbe, leben: 1, phase: 0 });
			}
		}

		function start() {
			if (art === 'schnee') teile = Array.from({ length: anzahl(22_000, 90) }, () => flocke());
			else if (art === 'konfetti') teile = Array.from({ length: anzahl(30_000, 60) }, () => schnipsel());
			else teile = [];
		}

		function schritt(jetzt: number) {
			if (!laeuft) return;
			// Gedeckelt: nach einem verdeckten Tab sonst ein Sprung über Sekunden.
			const dt = Math.min((jetzt - zuletzt) / 1000, 0.05);
			zuletzt = jetzt;
			ctx!.clearRect(0, 0, breite, hoehe);

			if (art === 'schnee') {
				// Weiß auf Weiß sähe niemand: im hellen Theme ein kühles Grau.
				const hell = document.documentElement.dataset.theme === 'light';
				ctx!.fillStyle = hell ? 'rgba(148, 170, 200, .75)' : 'rgba(255, 255, 255, .8)';
				for (const t of teile) {
					t.phase += dt;
					t.x += (t.vx + Math.sin(t.phase) * 12) * dt;
					t.y += t.vy * dt;
					if (t.y > hoehe + 5) Object.assign(t, flocke(true), { y: -5 });
					ctx!.beginPath();
					ctx!.arc(t.x, t.y, t.r, 0, Math.PI * 2);
					ctx!.fill();
				}
			} else if (art === 'konfetti') {
				for (const t of teile) {
					t.x += t.vx * dt;
					t.y += t.vy * dt;
					t.dreh += t.vdreh * dt;
					if (t.y > hoehe + 10) Object.assign(t, schnipsel(true), { y: -10 });
					ctx!.save();
					ctx!.translate(t.x, t.y);
					ctx!.rotate(t.dreh);
					ctx!.fillStyle = t.farbe;
					ctx!.globalAlpha = 0.75;
					ctx!.fillRect(-t.r, -t.r / 2.5, t.r * 2, t.r / 1.25);
					ctx!.restore();
				}
			} else if (art === 'fledermaeuse') {
				bisZumNaechsten -= dt;
				if (bisZumNaechsten <= 0 && teile.length < 3) {
					teile.push(fledermaus());
					bisZumNaechsten = zufall(4, 9);
				}
				ctx!.textAlign = 'center';
				ctx!.textBaseline = 'middle';
				teile = teile.filter((t) => t.x > -40 && t.x < breite + 40);
				for (const t of teile) {
					t.phase += dt * 9;
					t.x += t.vx * dt;
					t.y += Math.sin(t.phase / 3) * 25 * dt;
					ctx!.save();
					ctx!.translate(t.x, t.y);
					// Flügelschlag: vertikal stauchen, statt ein zweites Bild zu brauchen.
					ctx!.scale(t.vx < 0 ? -1 : 1, 0.75 + Math.abs(Math.sin(t.phase)) * 0.35);
					ctx!.globalAlpha = 0.85;
					ctx!.font = `${t.r}px sans-serif`;
					ctx!.fillText('🦇', 0, 0);
					ctx!.restore();
				}
			} else if (art === 'feuerwerk') {
				bisZumNaechsten -= dt;
				if (bisZumNaechsten <= 0) {
					rakete();
					bisZumNaechsten = zufall(0.6, 1.6);
				}
				teile = teile.filter((t) => t.leben > 0);
				for (const t of teile) {
					t.vy += 60 * dt;
					t.vx *= 1 - dt * 0.8;
					t.x += t.vx * dt;
					t.y += t.vy * dt;
					t.leben -= dt * 0.55;
					ctx!.globalAlpha = Math.max(t.leben, 0);
					ctx!.fillStyle = t.farbe;
					ctx!.beginPath();
					ctx!.arc(t.x, t.y, t.r, 0, Math.PI * 2);
					ctx!.fill();
				}
				ctx!.globalAlpha = 1;
			}
			rahmen = requestAnimationFrame(schritt);
		}

		function sichtbarkeit() {
			if (document.hidden) {
				laeuft = false;
				cancelAnimationFrame(rahmen);
			} else if (!laeuft) {
				laeuft = true;
				zuletzt = performance.now();
				rahmen = requestAnimationFrame(schritt);
			}
		}

		groesse();
		start();
		rahmen = requestAnimationFrame(schritt);
		const neuGroesse = () => { groesse(); start(); };
		window.addEventListener('resize', neuGroesse);
		document.addEventListener('visibilitychange', sichtbarkeit);
		return () => {
			laeuft = false;
			cancelAnimationFrame(rahmen);
			window.removeEventListener('resize', neuGroesse);
			document.removeEventListener('visibilitychange', sichtbarkeit);
		};
	});
</script>

<canvas bind:this={leinwand} class="saison-partikel" data-art={art} aria-hidden="true"></canvas>

<style>
	.saison-partikel {
		position: fixed;
		inset: 0;
		width: 100vw;
		height: 100vh;
		pointer-events: none;
		z-index: 1999;
	}
	@media print {
		.saison-partikel { display: none; }
	}
</style>
