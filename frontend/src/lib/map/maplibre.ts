/**
 * Zentraler MapLibre-Einstiegspunkt — bitte in Komponenten statt `maplibre-gl`
 * importieren.
 *
 * Hintergrund: maplibre-gl 6 lädt seinen Worker aus einer eigenen Datei und
 * leitet deren URL zur Laufzeit aus `import.meta.url` ab
 * (`new URL(`./${name}`, import.meta.url)`). Weil dieser Ausdruck dynamisch
 * ist, kann Vite ihn nicht statisch auflösen: `maplibre-gl-worker.mjs` landet
 * nicht im Build, und der Browser holt sich beim Start der Karte eine 404.
 *
 * Sichtbar wird das nur zur Hälfte — Rasterkacheln werden im Hauptthread
 * geladen, die Karte sieht also normal aus. Jede GeoJSON-/Vector-Quelle wird
 * dagegen im Worker geparst und bleibt leer: Routenlinien, Leitstellen-Grenzen
 * und die Landkreis-Auswahl verschwinden ersatzlos.
 *
 * Deshalb bündeln wir den Worker hier explizit über Vites `?worker&url`
 * (inklusive seines `maplibre-gl-shared.mjs`-Imports) und geben MapLibre die
 * dabei entstandene, gehashte Asset-URL vor.
 */
import * as maplibregl from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';

maplibregl.setWorkerUrl(workerUrl);

export * from 'maplibre-gl';
