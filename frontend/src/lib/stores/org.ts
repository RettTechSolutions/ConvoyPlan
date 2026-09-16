import { writable } from 'svelte/store';
import { authApi } from '$lib/api';
import { setActiveSlug } from '$lib/api/client';

export interface OrgContext {
    slug: string;
    org_id: string;
    org_name: string;
    user_id: string;
    user_role: 'beobachter' | 'fahrer' | 'planer' | 'admin';
    /** Eine Demo-Organisation — früher die `is_demo`-Claim im Token. */
    is_demo: boolean;
}

/**
 * Wer in welcher Organisation angemeldet ist.
 *
 * Diese Angaben kamen früher aus dem JWT, das im `localStorage` lag — das
 * Portal hat den Payload selbst dekodiert (`atob`). Seit die Sitzung im
 * HttpOnly-Cookie steckt, kommt JavaScript an den Inhalt nicht mehr heran,
 * und genau das ist der Zweck: was kein Skript lesen kann, kann auch keines
 * wegtragen.
 *
 * Also fragt der Store beim Server nach (`/api/auth/me`). Das ist nebenbei
 * die richtigere Quelle — die Rolle im Token war der Stand vom Anmelden, die
 * vom Server ist der von eben. Wer aus einer Organisation entfernt oder
 * herabgestuft wurde, merkt das jetzt beim nächsten Laden statt in bis zu
 * sieben Tagen.
 */
function createOrgStore() {
    const { subscribe, set } = writable<OrgContext | null>(null);

    return {
        subscribe,

        /**
         * Die Sitzung dieser Organisation beim Server erfragen.
         *
         * Gibt den Kontext zurück, wenn eine gültige Sitzung besteht, sonst
         * `null` — und `null` heißt für den Aufrufer: zur Anmeldung. Es wird
         * bewusst nicht zwischen „kein Cookie", „abgelaufen" und „nicht mehr
         * Mitglied" unterschieden; das Ergebnis ist in allen drei Fällen
         * dasselbe.
         */
        async load(slug: string): Promise<OrgContext | null> {
            setActiveSlug(slug);
            try {
                const me = await authApi.me();
                // Das Cookie gehört zu einer anderen Organisation, als die
                // URL behauptet — dann ist es für diese Seite keine Sitzung.
                if (!me.org_id || me.org_slug !== slug) {
                    set(null);
                    return null;
                }
                const ctx: OrgContext = {
                    slug,
                    org_id: me.org_id,
                    org_name: me.org_name ?? slug,
                    user_id: me.user_id,
                    user_role: (me.role ?? 'beobachter') as OrgContext['user_role'],
                    is_demo: me.is_demo,
                };
                set(ctx);
                return ctx;
            } catch {
                set(null);
                return null;
            }
        },

        clear(): void {
            set(null);
        },

        /** Die Sitzung dieser Organisation serverseitig beenden. */
        async logout(slug: string): Promise<void> {
            setActiveSlug(slug);
            try {
                await authApi.logout();
            } catch {
                /* Auch ein gescheitertes Abmelden darf die Oberfläche nicht
                   festhalten — der Kontext ist danach in jedem Fall weg. */
            }
            set(null);
        },
    };
}

export const orgStore = createOrgStore();
