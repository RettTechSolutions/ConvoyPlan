/**
 * Version store — fetches /api/version once and caches the result.
 *
 * The token is attached when one is present: /api/version is public, but it
 * only reveals the exact build (git-describe string + commit SHA) to
 * authenticated callers. Anonymous visitors get the release version only.
 */
import { getBaseUrl, getToken } from '$lib/api/client';

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
}

function createVersionStore(): VersionStore {
    let data = $state<VersionData>({ sha: null, version: null, latest: null, update_available: false });
    let loaded = $state(false);

    async function load(): Promise<void> {
        if (loaded) return;
        try {
            const token = getToken();
            const resp = await fetch(`${getBaseUrl()}/api/version`, {
                headers: token ? { Authorization: `Bearer ${token}` } : {},
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

    return {
        get data() { return data; },
        get loaded() { return loaded; },
        load,
    };
}

export const versionStore = createVersionStore();
