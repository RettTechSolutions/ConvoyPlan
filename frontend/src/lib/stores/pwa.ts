import { writable, derived } from 'svelte/store';

const DISMISSED_KEY = 'pwa-install-dismissed';
const DISMISS_TTL_MS = 30 * 24 * 60 * 60 * 1000;

function isDismissedRecently(): boolean {
	try {
		const raw = localStorage.getItem(DISMISSED_KEY);
		if (!raw) return false;
		return Date.now() - parseInt(raw, 10) < DISMISS_TTL_MS;
	} catch {
		return false;
	}
}

type PWAState = {
	deferredPrompt: BeforeInstallPromptEvent | null;
	isIOS: boolean;
	isStandalone: boolean;
	dismissed: boolean;
};

function createPWAStore() {
	const { subscribe, update } = writable<PWAState>({
		deferredPrompt: null,
		isIOS: false,
		isStandalone: false,
		dismissed: false,
	});

	let initialized = false;

	function init() {
		if (typeof window === 'undefined') return;
		if (initialized) return;
		initialized = true;

		const standalone = window.matchMedia('(display-mode: standalone)').matches;
		const ua = navigator.userAgent;
		const ios = /iphone|ipad|ipod/i.test(ua) && !(window as unknown as Record<string, unknown>)['MSStream'];
		const dismissed = isDismissedRecently();

		update(s => ({ ...s, isStandalone: standalone, isIOS: ios, dismissed }));

		if (standalone) return;

		const handler = (e: Event) => {
			e.preventDefault();
			update(s => ({ ...s, deferredPrompt: e as BeforeInstallPromptEvent }));
		};
		window.addEventListener('beforeinstallprompt', handler);
	}

	async function install(): Promise<'accepted' | 'dismissed' | 'unavailable'> {
		let result: 'accepted' | 'dismissed' | 'unavailable' = 'unavailable';
		update(s => {
			if (!s.deferredPrompt) return s;
			s.deferredPrompt.prompt();
			s.deferredPrompt.userChoice.then(({ outcome }) => {
				result = outcome;
				update(inner => ({ ...inner, deferredPrompt: null, dismissed: outcome === 'dismissed' }));
				if (outcome === 'dismissed') dismiss();
			});
			return s;
		});
		return result;
	}

	function dismiss() {
		try {
			localStorage.setItem(DISMISSED_KEY, String(Date.now()));
		} catch {}
		update(s => ({ ...s, dismissed: true }));
	}

	function clearDismiss() {
		try {
			localStorage.removeItem(DISMISSED_KEY);
		} catch {}
		update(s => ({ ...s, dismissed: false }));
	}

	return { subscribe, init, install, dismiss, clearDismiss };
}

export const pwaStore = createPWAStore();

// true when we should show any install UI
export const canShowInstall = derived(pwaStore, $s =>
	!$s.isStandalone && ($s.deferredPrompt !== null || $s.isIOS)
);
