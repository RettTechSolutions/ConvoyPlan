/**
 * Version store — fetches /api/version once and caches the result.
 */

interface VersionData {
    sha: string | null;
    version: string | null;
}

interface VersionStore {
    data: VersionData;
    loaded: boolean;
    load: () => Promise<void>;
}

function createVersionStore(): VersionStore {
    let data = $state<VersionData>({ sha: null, version: null });
    let loaded = $state(false);

    async function load(): Promise<void> {
        if (loaded) return;
        try {
            const resp = await fetch('/api/version');
            if (resp.ok) {
                const json = await resp.json() as VersionData;
                data = { sha: json.sha ?? null, version: json.version ?? null };
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
