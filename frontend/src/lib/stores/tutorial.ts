import { writable } from 'svelte/store';

/**
 * Steuert das Onboarding-Tutorial, das neuen Nutzern (Org wie Demo) beim
 * ersten Aufruf der Planungsseite alle Bereiche und Funktionen erklärt.
 *
 * Der "schon gesehen"-Status wird pro Org-Slug im localStorage gemerkt, damit
 * Demo- und echte Org-Sitzungen sich nicht gegenseitig überschreiben. Die
 * Versionsnummer im Key erlaubt es, das Tutorial nach größeren UI-Änderungen
 * erneut für alle anzuzeigen.
 */

const STORAGE_PREFIX = 'cp_tutorial_seen_v1__';

function storageKey(slug: string): string {
    return `${STORAGE_PREFIX}${slug}`;
}

function createTutorialStore() {
    // `open` steuert die Sichtbarkeit des Overlays.
    const { subscribe, set } = writable<boolean>(false);

    /** Wurde das Tutorial für diesen Slug bereits abgeschlossen/übersprungen? */
    function hasSeen(slug: string): boolean {
        if (typeof localStorage === 'undefined') return true;
        try {
            return localStorage.getItem(storageKey(slug)) === '1';
        } catch {
            return true;
        }
    }

    /** Merkt sich, dass das Tutorial für diesen Slug erledigt ist. */
    function markSeen(slug: string): void {
        if (typeof localStorage === 'undefined') return;
        try {
            localStorage.setItem(storageKey(slug), '1');
        } catch {
            /* localStorage nicht verfügbar – dann zeigen wir es ggf. erneut */
        }
    }

    return {
        subscribe,

        /** Öffnet das Tutorial sofort (z. B. über den „?"-Hilfe-Button). */
        open(): void {
            set(true);
        },

        /** Schließt das Overlay. */
        close(): void {
            set(false);
        },

        /**
         * Zeigt das Tutorial automatisch beim ersten Besuch. Gibt `true`
         * zurück, wenn es geöffnet wurde.
         */
        openIfFirstVisit(slug: string): boolean {
            if (hasSeen(slug)) return false;
            set(true);
            return true;
        },

        /** Beendet das Tutorial und merkt sich den Slug als „gesehen". */
        finish(slug: string): void {
            markSeen(slug);
            set(false);
        },

        hasSeen,
        markSeen,
    };
}

export const tutorialStore = createTutorialStore();
