// Shared in-app attention signal (vibration + short tone sequence) for the
// tracking views — used for TH/Ausfall alerts and route-point announcements.

let audioCtx: AudioContext | null = null;

function beep(urgent: boolean) {
	const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
	if (!Ctx) return;
	audioCtx ??= new Ctx();
	const ctx = audioCtx;
	const tones = urgent ? [880, 660, 880] : [660, 880];
	tones.forEach((freq, i) => {
		const osc = ctx.createOscillator();
		const gain = ctx.createGain();
		osc.type = 'sine';
		osc.frequency.value = freq;
		gain.gain.value = 0.001;
		osc.connect(gain).connect(ctx.destination);
		const t = ctx.currentTime + i * 0.22;
		gain.gain.setValueAtTime(0.0001, t);
		gain.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
		gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.2);
		osc.start(t);
		osc.stop(t + 0.22);
	});
}

export function notifySignal(urgent = false) {
	try { navigator.vibrate?.(urgent ? [200, 100, 200, 100, 200] : [200, 100, 200]); } catch { /* unsupported */ }
	try { beep(urgent); } catch { /* audio blocked */ }
}
