import { writable } from 'svelte/store';
import { authApi } from '$lib/api';

interface AuthState {
    token: string | null;
    is_superadmin: boolean;
}

function parseToken(token: string): { is_superadmin: boolean } {
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        return { is_superadmin: !!payload.is_superadmin };
    } catch {
        return { is_superadmin: false };
    }
}

function createAuthStore() {
    const { subscribe, set } = writable<AuthState>({ token: null, is_superadmin: false });

    const init = () => {
        const token = localStorage.getItem('token');
        if (token) {
            set({ token, ...parseToken(token) });
        } else {
            set({ token: null, is_superadmin: false });
        }
    };

    const login = async (email: string, password: string) => {
        const data = await authApi.login(email, password);
        localStorage.setItem('token', data.access_token);
        set({ token: data.access_token, ...parseToken(data.access_token) });
    };

    const logout = () => {
        localStorage.removeItem('token');
        set({ token: null, is_superadmin: false });
    };

    return { subscribe, init, login, logout };
}

export const auth = createAuthStore();
export const isLoggedIn = { subscribe: (fn: (v: boolean) => void) => auth.subscribe((s) => fn(!!s.token)) };
