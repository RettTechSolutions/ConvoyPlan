/**
 * Version store — fetches /api/version once and caches the result.
 *
 * Die Sitzung wird mitgeschickt, falls eine besteht: /api/version ist
 * öffentlich, verrät den exakten Build (git-describe + Commit-SHA) aber nur
 * an angemeldete Aufrufer. Anonyme Besucher bekommen nur die Release-Version.
 */
import { getBaseUrl, authHeaders } from '$lib/api/client';

interface VersionData {
    sha: string | null;
    version: string | null;
    latest: string | null;
    update_available: boolean;
}

interface VersionStore {
    data: VersionData;
    loaded: boolean;
    load: () => Promise<void>;
    uebernehme: (update_available: boolean, latest: string | null) => void;
}

function createVersionStore(): VersionStore {
    let data = $state<VersionData>({ sha: null, version: null, latest: null, update_available: false });
    let loaded = $state(false);

    async function load(): Promise<void> {
        if (loaded) return;
        try {
            const resp = await fetch(`${getBaseUrl()}/api/version`, {
                credentials: 'same-origin',
                headers: authHeaders(),
            });
            if (resp.ok) {
                const json = await resp.json() as Partial<VersionData>;
                data = {
                    sha: json.sha ?? null,
                    version: json.version ?? null,
                    latest: json.latest ?? null,
                    update_available: json.update_available ?? false,
                };
            }
        } catch {
            // silently ignore — version info is non-critical
        } finally {
            loaded = true;
        }
    }

    /** Frischeren Stand aus der Admin-Karte übernehmen (`/api/admin/update-status`). */
    function uebernehme(update_available: boolean, latest: string | null): void {
        data = { ...data, update_available, latest };
        loaded = true;
    }

    return {
        get data() { return data; },
        get loaded() { return loaded; },
        load,
        uebernehme,
    };
}

export const versionStore = createVersionStore();
