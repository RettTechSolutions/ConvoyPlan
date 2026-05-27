import { writable } from 'svelte/store';

export interface OrgContext {
    slug: string;
    org_id: string;
    org_name: string;
    user_id: string;
    user_role: 'beobachter' | 'fahrer' | 'planer' | 'admin';
}

function createOrgStore() {
    const { subscribe, set } = writable<OrgContext | null>(null);

    return {
        subscribe,

        /** Wird vom o/[slug]/+layout.svelte aufgerufen */
        setFromToken(slug: string, orgName: string, token: string): void {
            try {
                const payload = JSON.parse(atob(token.split('.')[1]));
                set({
                    slug,
                    org_id: payload.org_id,
                    org_name: orgName,
                    user_id: payload.sub,
                    user_role: payload.role ?? 'beobachter',
                });
            } catch {
                set(null);
            }
        },

        clear(): void {
            set(null);
        },

        getToken(slug: string): string | null {
            return localStorage.getItem(`token__${slug}`);
        },

        setToken(slug: string, token: string): void {
            localStorage.setItem(`token__${slug}`, token);
        },

        removeToken(slug: string): void {
            localStorage.removeItem(`token__${slug}`);
        },
    };
}

export const orgStore = createOrgStore();
