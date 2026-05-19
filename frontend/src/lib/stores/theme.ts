import { writable } from 'svelte/store';

type Theme = 'dark' | 'light';

function createThemeStore() {
    const { subscribe, set, update } = writable<Theme>('dark');

    function init() {
        if (typeof window === 'undefined') return;
        const saved = localStorage.getItem('convoyplan-theme');
        if (saved === 'light' || saved === 'dark') set(saved);
    }

    function toggle() {
        update(current => {
            const next: Theme = current === 'dark' ? 'light' : 'dark';
            if (typeof window !== 'undefined') {
                document.documentElement.setAttribute('data-theme', next);
                try { localStorage.setItem('convoyplan-theme', next); } catch (_) {}
            }
            return next;
        });
    }

    return { subscribe, set, init, toggle };
}

export const themeStore = createThemeStore();
