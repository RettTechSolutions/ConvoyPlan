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

    /** Store a token that was already validated (e.g. after MFA verify). */
    const setToken = (token: string) => {
        localStorage.setItem('token', token);
        set({ token, ...parseToken(token) });
    };

    /**
     * Standard credential-based login.
     * Returns `{ mfa_required: true, mfa_token }` when MFA is enabled —
     * the caller must then call `mfaVerify()` and pass the result to `setToken()`.
     */
    const login = async (email: string, password: string) => {
        const data = await authApi.login(email, password);
        if (data.mfa_required && data.mfa_token) {
            return { mfa_required: true as const, mfa_token: data.mfa_token };
        }
        if (data.access_token) {
            setToken(data.access_token);
        }
        return { mfa_required: false as const };
    };

    const mfaVerify = async (mfa_token: string, code: string) => {
        const data = await authApi.mfaVerify(mfa_token, code);
        if (data.access_token) {
            setToken(data.access_token);
        }
    };

    const logout = () => {
        localStorage.removeItem('token');
        set({ token: null, is_superadmin: false });
    };

    return { subscribe, init, login, mfaVerify, setToken, logout };
}

export const auth = createAuthStore();
export const isLoggedIn = { subscribe: (fn: (v: boolean) => void) => auth.subscribe((s) => fn(!!s.token)) };
