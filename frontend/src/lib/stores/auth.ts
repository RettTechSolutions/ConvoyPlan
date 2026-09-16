import { writable } from 'svelte/store';
import { authApi } from '$lib/api';
import { setActiveSlug } from '$lib/api/client';

interface AuthState {
    /**
     * `false`, solange der Server noch nicht geantwortet hat.
     *
     * Dieser dritte Zustand ist neu und nötig: früher stand das Token im
     * `localStorage` und war damit *synchron* verfügbar — das Root-Layout
     * konnte `auth.init()` vor dem ersten `onMount` der Kinder aufrufen.
     * Eine Sitzung im HttpOnly-Cookie lässt sich nur durch eine Anfrage
     * feststellen, und die dauert. Wer „angemeldet?" fragt, bevor `ready`
     * gesetzt ist, bekäme sonst ein falsches Nein und würde zur Anmeldung
     * umleiten, obwohl die Sitzung besteht.
     */
    ready: boolean;
    is_authenticated: boolean;
    is_superadmin: boolean;
    email: string | null;
}

const LEER: AuthState = {
    ready: false,
    is_authenticated: false,
    is_superadmin: false,
    email: null,
};

function createAuthStore() {
    const { subscribe, set } = writable<AuthState>(LEER);

    /** Die organisationslose (Superadmin-)Sitzung beim Server erfragen. */
    const init = async (): Promise<boolean> => {
        setActiveSlug(null);
        try {
            const me = await authApi.me();
            set({
                ready: true,
                is_authenticated: true,
                is_superadmin: me.is_superadmin,
                email: me.email,
            });
            return true;
        } catch {
            set({ ...LEER, ready: true });
            return false;
        }
    };

    /**
     * Anmeldung ohne Organisation (Superadmin).
     *
     * Die Antwort trägt weiterhin ein `access_token` — für Skripte und
     * API-Clients, die den Bearer-Weg nutzen. Das Portal rührt es nicht an:
     * die Sitzung steht im selben Antwort-Schritt bereits als HttpOnly-Cookie,
     * und ein zweites Mal daneben im `localStorage` wäre genau das, was diese
     * Umstellung abgeschafft hat.
     */
    const login = async (email: string, password: string) => {
        const data = await authApi.login(email, password);
        if (data.mfa_required && data.mfa_token) {
            return { mfa_required: true as const, mfa_token: data.mfa_token };
        }
        await init();
        return { mfa_required: false as const };
    };

    const mfaVerify = async (mfa_token: string, code: string) => {
        await authApi.mfaVerify(mfa_token, code);
        await init();
    };

    const logout = async () => {
        setActiveSlug(null);
        try {
            await authApi.logout();
        } catch {
            /* Siehe orgStore.logout — die Oberfläche meldet trotzdem ab. */
        }
        set({ ...LEER, ready: true });
    };

    return { subscribe, init, login, mfaVerify, logout };
}

export const auth = createAuthStore();