<script lang="ts">
    /**
     * Admin → System → Kartenregion.
     *
     * Ruhezustand: aktuelle Region, Extract-Größe, Plattenbelegung (beide aus
     * `regionApi.preview(current.url)` — es gibt keinen eigenen Endpunkt dafür,
     * `preview` ist aber ausdrücklich nebenwirkungsfrei, siehe app/api/routes/region.py).
     * Auswahl: Schnellauswahl (die vier Installer-Regionen, URL deterministisch
     * gebaut — kein Warten auf den 555-Einträge-Index) plus Suche über den
     * vollen Geofabrik-Index (lazy geladen, erst bei Bedarf).
     * Wechsel: Phase kommt ausschließlich aus GET /region/status — ein Reload
     * mitten im Wechsel zeigt denselben Zustand, weil hier nichts aus
     * Komponentenzustand rekonstruiert wird. Das Terminal darunter speist sich
     * aus GET /region/log (SSE, `region.log` des Updaters): das ist die
     * vollständige Ausgabe inklusive Import-Container. Aus den Phasenmeldungen
     * allein bestünde es bei einem zweistündigen Import aus einer Zeile.
     */
    import { onDestroy, onMount } from 'svelte';
    import {
        regionApi,
        type RegionCurrent,
        type RegionEntry,
        type RegionPhase,
        type RegionPreview,
        type RegionStatus,
    } from '$lib/api';
    import { ApiError } from '$lib/api/client';

    // ── Ruhezustand ──────────────────────────────────────────────────────────
    let current = $state<RegionCurrent | null>(null);
    let currentPreview = $state<RegionPreview | null>(null);
    let loadingCurrent = $state(true);
    let currentError = $state('');

    // ── Auswahl ──────────────────────────────────────────────────────────────
    let showPicker = $state(false);
    let regions = $state<RegionEntry[] | null>(null);
    let regionsLoading = $state(false);
    let regionsError = $state('');
    let search = $state('');

    // Deterministisch gebaut (Schema + Host + Pfad, siehe geofabrik.validate_region_url),
    // damit die Schnellauswahl nicht erst auf den vollen 555-Einträge-Index warten muss.
    const QUICK_PICKS: { id: string; label: string }[] = [
        { id: 'europe/dach', label: 'DACH (Deutschland, Österreich, Schweiz)' },
        { id: 'europe/germany', label: 'Deutschland' },
        { id: 'europe/germany/bayern', label: 'Bayern' },
        { id: 'europe/germany/berlin', label: 'Berlin' },
    ];

    const filteredRegions = $derived.by(() => {
        if (!regions) return [];
        const q = search.trim().toLowerCase();
        if (q.length < 2) return [];
        return regions
            .filter((r) => r.path.toLowerCase().includes(q) || r.name.toLowerCase().includes(q))
            .slice(0, 100);
    });

    // ── Auswahl-Liste ────────────────────────────────────────────────────────
    // Mehrere Regionen kombinierbar (Deutschland + Polen statt ganz Europa),
    // die der Updater zu einer Karte verschmilzt. Schnellauswahl ERSETZT diese
    // Liste ("einfach DACH"), Suchtreffer FÜGEN HINZU.
    let selectedList = $state<RegionEntry[]>([]);

    // ── Vorab-Rechnung ───────────────────────────────────────────────────────
    let preview = $state<RegionPreview | null>(null);
    let previewLoading = $state(false);
    let previewError = $state('');

    // ── Wechsel / Status ─────────────────────────────────────────────────────
    let status = $state<RegionStatus>({ phase: 'idle' });
    let switching = $state(false);
    let switchError = $state('');
    let cancelling = $state(false);
    let cancelError = $state('');
    let logLines = $state<string[]>([]);
    let logError = $state('');
    // $state, weil das Terminal am offenen Strom erkennt, ob es noch etwas
    // erwarten darf (Cursor) — die Zuweisung muss also ein Rendern auslösen.
    let logSource = $state<EventSource | null>(null);
    let logContainer = $state<HTMLDivElement | null>(null);
    // true nach "Schließen" auf einem abgeschlossenen/fehlgeschlagenen Wechsel —
    // blendet die Phasenkarte lokal aus, obwohl der Server denselben Endstatus
    // bis zum nächsten Wechsel weiter meldet.
    let dismissed = $state(false);
    let timer: ReturnType<typeof setInterval> | null = null;

    // 'merging' MUSS hier stehen: fehlt es, wird `busy` waehrend des
    // Zusammenfuehrens false, Phasenkarte und Live-Log verschwinden — und bei
    // 'importing' tauchen sie wieder auf. Fuer den Operator sieht das aus, als
    // sei der Wechsel abgestuerzt. Bei grossen Kombinationen dauert die Phase
    // Minuten.
    const ACTIVE_PHASES: RegionPhase[] = [
        'checking', 'downloading', 'merging', 'importing', 'switching', 'cleaning',
    ];
    // 'merging' bewusst NICHT abbrechbar: switch-region.sh prueft region.cancel
    // erst nach dem Merge wieder, ein Knopf waere hier ohne Wirkung.
    const CANCELLABLE_PHASES: RegionPhase[] = ['checking', 'downloading', 'importing'];
    const PHASE_LABELS: Record<RegionPhase, string> = {
        idle: 'Bereit',
        checking: 'Phase 1/5 — Prüfe Verfügbarkeit und Plattenplatz',
        downloading: 'Phase 2/5 — Lade Extract herunter',
        // Nur bei kombinierten Regionen (mehr als ein Bestandteil) — daher
        // ohne eigene Ordinalzahl, um keine falsche Gesamtschrittzahl zu
        // suggerieren (Einzelauswahl durchläuft diese Phase nie).
        merging: 'Führe Extracts zu einer Karte zusammen',
        importing: 'Phase 3/5 — Baue Routing-Graph (Routing bleibt währenddessen aktiv)',
        switching: 'Phase 4/5 — Schwenke auf die neue Region',
        cleaning: 'Phase 5/5 — Räume alte Daten auf',
        done: 'Abgeschlossen',
        failed: 'Fehlgeschlagen',
    };

    const busy = $derived(!dismissed && ACTIVE_PHASES.includes(status.phase));
    const finished = $derived(!dismissed && (status.phase === 'done' || status.phase === 'failed'));
    const showSwitchPanel = $derived(busy || finished);
    const canCancel = $derived(busy && CANCELLABLE_PHASES.includes(status.phase));
    const blocked = $derived(preview?.verdict === 'reicht nicht');

    onMount(async () => {
        await loadCurrent();
        await refreshStatus();
        // Läuft (oder endete gerade) ein Wechsel, den jemand anders oder ein
        // früherer Seitenaufruf angestoßen hat: das Log gehört trotzdem hierher.
        if (showSwitchPanel) await startLogStream();
        timer = setInterval(refreshStatus, 3000);
    });
    onDestroy(() => {
        if (timer) clearInterval(timer);
        stopLogStream();
    });

    function stopLogStream() {
        if (logSource) {
            logSource.close();
            logSource = null;
        }
    }

    async function startLogStream() {
        stopLogStream();
        logLines = [];
        logError = '';
        const es = await regionApi.logStream();
        if (!es) {
            logError = 'Log-Verbindung nicht möglich — bitte neu anmelden.';
            return;
        }
        logSource = es;
        es.onmessage = (e) => {
            logLines = [...logLines, e.data];
            // ans Ende scrollen, nachdem Svelte die neue Zeile gerendert hat
            setTimeout(() => {
                if (logContainer) logContainer.scrollTop = logContainer.scrollHeight;
            }, 0);
        };
        es.addEventListener('done', (e) => {
            stopLogStream();
            // "timeout": der Strom hat sein Zeitlimit erreicht, der Wechsel
            // läuft aber noch. Neu aufbauen — der Strom liest wieder ab Byte 0,
            // deshalb entstehen dabei keine doppelten Zeilen.
            if ((e as MessageEvent).data === 'timeout' && busy) void startLogStream();
        });
        es.onerror = () => {
            // Verbindung weg (Backend startet neu, Proxy-Timeout). Nicht selbst
            // weiterverbinden lassen: EventSource würde von Byte 0 neu lesen und
            // alles doppelt anhängen. Stattdessen ein Knopf zum Neuladen.
            stopLogStream();
            logError = 'Log-Verbindung getrennt.';
        };
    }

    async function loadCurrent() {
        loadingCurrent = true;
        currentError = '';
        try {
            current = await regionApi.current();
            currentPreview = await regionApi.preview([current.url]);
        } catch (e: unknown) {
            currentError = e instanceof Error ? e.message : 'Aktuelle Region konnte nicht geladen werden';
        } finally {
            loadingCurrent = false;
        }
    }

    async function refreshStatus() {
        try {
            const wasIdle = !ACTIVE_PHASES.includes(status.phase);
            status = await regionApi.status();
            // Ein Wechsel, der nicht in diesem Tab ausgelöst wurde (zweites
            // Fenster, anderer Superadmin): Log nachträglich anhängen.
            if (wasIdle && ACTIVE_PHASES.includes(status.phase) && !logSource) {
                dismissed = false;
                await startLogStream();
            }
        } catch {
            // Kurzfristig nicht lesbar (z. B. Backend startet gerade neu) —
            // kein Fehlerzustand, der naechste Poll versucht es erneut.
        }
    }

    function openPicker() {
        showPicker = true;
    }

    function closePicker() {
        showPicker = false;
        selectedList = [];
        preview = null;
        previewError = '';
        search = '';
    }

    async function loadRegions() {
        if (regions || regionsLoading) return;
        regionsLoading = true;
        regionsError = '';
        try {
            regions = await regionApi.list();
        } catch (e: unknown) {
            regionsError = e instanceof Error ? e.message : 'Regionsliste konnte nicht geladen werden';
        } finally {
            regionsLoading = false;
        }
    }

    function quickPickUrl(id: string): string {
        return `https://download.geofabrik.de/${id}-latest.osm.pbf`;
    }

    // Schnellauswahl ERSETZT die Auswahl — gedacht als "einfach DACH", nicht
    // als weiterer Bestandteil einer Kombination.
    async function chooseQuick(qp: { id: string; label: string }) {
        selectedList = [{ id: qp.id, name: qp.label, path: qp.label, url: quickPickUrl(qp.id) }];
        await refreshPreview();
    }

    // Ein Suchtreffer FÜGT HINZU statt zu ersetzen — das ist der Kern der
    // Mehrfachauswahl (Deutschland + Polen statt ganz Europa).
    async function addRegion(entry: RegionEntry) {
        if (selectedList.some((e) => e.id === entry.id)) return;
        selectedList = [...selectedList, entry];
        await refreshPreview();
    }

    // Entfernt eine Region aus der Auswahl — per Marken-Kreuz oder per
    // Überlappungshinweis (dort mit dem Pfad der Unterregion als `id`, der
    // Geofabrik-Pfad und `entry.id` sind dasselbe Format).
    async function removeRegion(id: string) {
        selectedList = selectedList.filter((e) => e.id !== id);
        await refreshPreview();
    }

    // Bei jeder Änderung der Auswahl neu abgerufen — das ist der Schutz gegen
    // die freie Mehrfachauswahl: Summe und Urteil laufen live mit, bevor der
    // Wechsel überhaupt gestartet wird.
    async function refreshPreview() {
        if (selectedList.length === 0) {
            preview = null;
            previewError = '';
            previewLoading = false;
            return;
        }
        preview = null;
        previewError = '';
        previewLoading = true;
        try {
            preview = await regionApi.preview(selectedList.map((e) => e.url));
        } catch (e: unknown) {
            previewError = e instanceof Error ? e.message : 'Vorab-Rechnung fehlgeschlagen';
        } finally {
            previewLoading = false;
        }
    }

    async function startSwitch() {
        if (selectedList.length === 0 || blocked || switching) return;
        switchError = '';
        switching = true;
        try {
            await regionApi.switch(selectedList.map((e) => e.url));
            showPicker = false;
            selectedList = [];
            preview = null;
            dismissed = false;
            await startLogStream();
            await refreshStatus();
        } catch (e: unknown) {
            if (e instanceof ApiError && e.status === 409) {
                switchError = 'Es läuft bereits ein Update oder Regionswechsel.';
            } else {
                switchError = e instanceof Error ? e.message : 'Regionswechsel konnte nicht gestartet werden';
            }
        } finally {
            switching = false;
        }
    }

    async function cancelSwitch() {
        cancelError = '';
        cancelling = true;
        try {
            await regionApi.cancel();
            await refreshStatus();
        } catch (e: unknown) {
            cancelError = e instanceof Error ? e.message : 'Abbrechen fehlgeschlagen';
        } finally {
            cancelling = false;
        }
    }

    async function closeFinished() {
        dismissed = true;
        stopLogStream();
        logLines = [];
        logError = '';
        await loadCurrent();
    }

    function bytes(value: number | null | undefined): string {
        if (value == null) return '–';
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        let size = value;
        let unit = 0;
        while (Math.abs(size) >= 1024 && unit < units.length - 1) {
            size /= 1024;
            unit++;
        }
        return `${size.toFixed(size >= 100 || unit === 0 ? 0 : 1).replace('.', ',')} ${units[unit]}`;
    }

    function formatDuration([low, high]: [number, number]): string {
        const fmt = (m: number) => (m >= 60 ? `${(m / 60).toFixed(1).replace('.', ',')} Std.` : `${m} Min.`);
        return `${fmt(low)} – ${fmt(high)}`;
    }
</script>

<div class="section region-card">
    <div class="section-header">
        <strong>Kartenregion</strong>
        {#if !showSwitchPanel && !loadingCurrent}
            <button class="btn-small" onclick={loadCurrent}>↺ Aktualisieren</button>
        {/if}
    </div>

    {#if currentError}
        <div class="error-bar">{currentError} <button onclick={() => (currentError = '')}>✕</button></div>
    {/if}

    {#if showSwitchPanel}
        <!-- ── Wechsel läuft oder ist gerade beendet ── -->
        <div class="phase-row">
            <span
                class="badge"
                class:badge-update={busy}
                class:badge-ok={status.phase === 'done'}
                class:badge-warn={status.phase === 'failed'}
            >
                {#if busy}<span class="spinner"></span>{/if}
                {PHASE_LABELS[status.phase]}
            </span>
            {#if status.at}<span class="hint">{new Date(status.at).toLocaleString('de-DE')}</span>{/if}
        </div>

        {#if status.phase === 'failed'}
            <p class="reassurance">
                Die bisherige Region läuft unverändert weiter. Verloren sind nur Zeit und Plattenplatz.
            </p>
        {/if}

        <div class="update-terminal" bind:this={logContainer}>
            {#each logLines as line}
                <div class="log-line">{line}</div>
            {/each}
            {#if logLines.length === 0 && !logError}
                <div class="log-line">Warte auf Ausgabe des Updaters…</div>
            {/if}
            {#if busy && logSource}
                <div class="log-cursor">▌</div>
            {:else if !busy}
                <div class="log-line log-done">─── {status.phase === 'failed' ? 'Fehlgeschlagen' : 'Fertig'} ───</div>
            {/if}
        </div>
        {#if logError}
            <div class="error-bar">{logError} <button onclick={startLogStream}>↺</button></div>
        {/if}

        <div class="switch-actions">
            {#if canCancel}
                <button class="btn-secondary" onclick={cancelSwitch} disabled={cancelling}>
                    {cancelling ? '…' : 'Abbrechen'}
                </button>
            {/if}
            {#if finished}
                <button class="btn-small" onclick={closeFinished}>Schließen</button>
            {/if}
        </div>
        {#if cancelError}
            <div class="error-bar">{cancelError} <button onclick={() => (cancelError = '')}>✕</button></div>
        {/if}
    {:else}
        <!-- ── Ruhezustand ── -->
        {#if loadingCurrent}
            <p class="hint">Lade…</p>
        {:else if current}
            <div class="update-grid">
                <div class="update-row">
                    <span class="update-label">Aktuelle Region</span>
                    <code>{current.filename}</code>
                </div>
                <div class="update-row">
                    <span class="update-label">Extract-Größe</span>
                    <span>{currentPreview ? bytes(currentPreview.extract_bytes) : '–'}</span>
                </div>
                <div class="update-row">
                    <span class="update-label">Frei auf Platte</span>
                    <span>{currentPreview ? bytes(currentPreview.disk_free_bytes) : '–'}</span>
                </div>
            </div>

            {#if !showPicker}
                <div style="margin-top:1rem">
                    <button class="btn-primary" onclick={openPicker}>Region wechseln</button>
                </div>
            {/if}
        {/if}

        {#if showPicker}
            <div class="region-picker">
                <div class="quick-picks">
                    {#each QUICK_PICKS as qp}
                        <button
                            class="btn-small"
                            class:active={selectedList.some((e) => e.id === qp.id)}
                            onclick={() => chooseQuick(qp)}
                        >{qp.label}</button>
                    {/each}
                </div>

                {#if selectedList.length > 1}
                    <!-- Nur bei kombinierter Auswahl — bei genau einer Region soll
                         die Karte wie bisher aussehen (keine Marken-Leiste). -->
                    <div class="chip-row">
                        {#each selectedList as entry (entry.id)}
                            <span class="chip">
                                {entry.path}
                                <button
                                    type="button"
                                    class="chip-remove"
                                    onclick={() => removeRegion(entry.id)}
                                    aria-label={`${entry.path} entfernen`}
                                >✕</button>
                            </span>
                        {/each}
                    </div>
                {/if}

                <input
                    type="text"
                    class="region-search"
                    placeholder="Region suchen (z. B. „Bayern“ oder „France“)…"
                    bind:value={search}
                    onfocus={loadRegions}
                />

                {#if regionsLoading}
                    <p class="hint">Lade Regionsliste…</p>
                {:else if regionsError}
                    <div class="error-bar">{regionsError} <button onclick={loadRegions}>↺</button></div>
                {:else if search.trim().length < 2}
                    <p class="hint">Mindestens 2 Zeichen eingeben, um in über 500 Regionen zu suchen — oder eine Schnellauswahl oben verwenden.</p>
                {:else}
                    <div class="region-list">
                        {#each filteredRegions as r (r.id)}
                            <button
                                class="region-item"
                                class:active={selectedList.some((e) => e.id === r.id)}
                                onclick={() => addRegion(r)}
                            >{r.path}</button>
                        {/each}
                        {#if filteredRegions.length === 0}
                            <p class="hint">Keine Treffer.</p>
                        {/if}
                    </div>
                {/if}

                {#if selectedList.length > 0}
                    <div class="preview-box">
                        {#if selectedList.length === 1}
                            <div class="preview-title">{selectedList[0].path}</div>
                        {:else}
                            <div class="preview-title">Kombinierte Region — {selectedList.length} Bestandteile</div>
                        {/if}
                        {#if previewLoading}
                            <p class="hint">Berechne Ressourcenbedarf…</p>
                        {:else if previewError}
                            <div class="error-bar">{previewError} <button onclick={refreshPreview}>↺</button></div>
                        {:else if preview}
                            {#if preview.overlapping.length > 0}
                                <div class="overlap-hint">
                                    <p>
                                        Manche Regionen überlappen — das ist nicht falsch (der Merge dedupliziert
                                        automatisch), verschwendet aber Download und Zeit:
                                    </p>
                                    {#each preview.overlapping as [parentPath, childPath]}
                                        <div class="overlap-row">
                                            <code>{parentPath}</code> enthält bereits <code>{childPath}</code>
                                            <button class="btn-small" onclick={() => removeRegion(childPath)}>
                                                Unterregion entfernen
                                            </button>
                                        </div>
                                    {/each}
                                </div>
                            {/if}
                            <div class="update-grid">
                                {#if preview.composed}
                                    <div class="update-row">
                                        <span class="update-label">Bestandteile</span>
                                        <span>{preview.sources.join(', ')}</span>
                                    </div>
                                {/if}
                                <div class="update-row">
                                    <span class="update-label">RAM benötigt</span>
                                    <span>{bytes(preview.ram_needed_bytes)}</span>
                                </div>
                                <div class="update-row">
                                    <span class="update-label">RAM verfügbar</span>
                                    <span>
                                        {bytes(preview.ram_available_bytes)}
                                        <span class="hint">
                                            + {bytes(preview.ram_reclaimable_bytes)} durch Verkleinern des laufenden
                                            GraphHopper während des Imports (effektiv {bytes(preview.ram_effective_available_bytes)})
                                        </span>
                                    </span>
                                </div>
                                <div class="update-row">
                                    <span class="update-label">Platte benötigt</span>
                                    <span>{bytes(preview.disk_needed_bytes)}</span>
                                </div>
                                <div class="update-row">
                                    <span class="update-label">Platte frei</span>
                                    <span>{bytes(preview.disk_free_bytes)}</span>
                                </div>
                                <div class="update-row">
                                    <span class="update-label">Geschätzte Dauer</span>
                                    <span>{formatDuration(preview.duration_minutes)}</span>
                                </div>
                                <div class="update-row">
                                    <span class="update-label">Einschätzung</span>
                                    <span
                                        class="badge"
                                        class:badge-ok={preview.verdict === 'ok'}
                                        class:badge-update={preview.verdict === 'knapp'}
                                        class:badge-warn={preview.verdict === 'reicht nicht'}
                                    >{preview.verdict}</span>
                                </div>
                            </div>
                            <p class="hint" style="margin-top:.5rem">{preview.reason}</p>

                            <div class="switch-actions">
                                <button class="btn-primary" disabled={blocked || switching} onclick={startSwitch}>
                                    {switching ? '…' : 'Wechsel starten'}
                                </button>
                                <button class="btn-secondary" onclick={closePicker}>Abbrechen</button>
                            </div>
                            {#if switchError}
                                <div class="error-bar">{switchError} <button onclick={() => (switchError = '')}>✕</button></div>
                            {/if}
                        {/if}
                    </div>
                {/if}
            </div>
        {/if}
    {/if}
</div>

<style>
    .section {
        background: var(--surface-1);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1rem;
        box-shadow: var(--shadow);
        overflow-x: auto;
    }
    .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: .75rem;
        font-size: var(--text-sm);
        font-weight: 500;
        color: var(--text-1);
    }
    .hint { color: var(--text-muted); font-size: var(--text-sm); }
    .error-bar { background: var(--color-primary-hover); color: white; padding: .4rem .75rem; border-radius: 4px; margin-bottom: 1rem; display: flex; justify-content: space-between; gap: .5rem; }
    .error-bar button { background: none; border: none; color: white; cursor: pointer; }
    code { background: var(--surface-2); padding: .1rem .3rem; border-radius: 3px; font-size: var(--text-xs); font-family: monospace; color: var(--text-1); }

    .btn-small { padding: .2rem .5rem; font-size: var(--text-xs); border-radius: 3px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-2); cursor: pointer; }
    .btn-small:hover { background: var(--surface-1); }
    .btn-small.active { background: var(--color-primary); color: white; border-color: var(--color-primary); }
    .btn-primary { padding: .5rem 1rem; background: var(--color-primary); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
    .btn-primary:disabled { opacity: .5; cursor: not-allowed; }
    .btn-primary:hover:not(:disabled) { background: var(--color-primary-hover); }
    .btn-secondary { padding: .5rem 1rem; background: transparent; color: var(--text-2); border: 1px solid var(--border); border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
    .btn-secondary:hover:not(:disabled) { background: var(--surface-2); }
    .btn-secondary:disabled { opacity: .5; cursor: not-allowed; }

    .update-grid { display: flex; flex-direction: column; gap: .6rem; }
    .update-row { display: flex; align-items: center; gap: .75rem; font-size: var(--text-sm); flex-wrap: wrap; }
    .update-label { width: 130px; color: var(--text-muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .04em; flex-shrink: 0; }

    .badge { display: inline-block; padding: .15rem .5rem; border-radius: 3px; font-size: var(--text-xs); font-weight: 600; }
    .badge-ok { background: rgba(107,127,77,.2); color: #a8c070; border: 1px solid rgba(107,127,77,.4); }
    .badge-update { background: rgba(210,120,30,.2); color: #e8a050; border: 1px solid rgba(210,120,30,.4); }
    .badge-warn { background: rgba(180,60,40,.15); color: var(--color-primary); border: 1px solid rgba(180,60,40,.3); }
    .spinner { display: inline-block; width: 12px; height: 12px; border: 2px solid rgba(255,255,255,.3); border-top-color: currentColor; border-radius: 50%; animation: spin .7s linear infinite; vertical-align: middle; margin-right: .3rem; }
    @keyframes spin { to { transform: rotate(360deg); } }

    .update-terminal {
        margin-top: .75rem;
        background: #0d1117;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: .75rem 1rem;
        font-family: 'Menlo', 'Consolas', 'Monaco', monospace;
        font-size: 12px;
        line-height: 1.6;
        color: #c9d1d9;
        max-height: 260px;
        overflow-y: auto;
        scroll-behavior: smooth;
    }
    .log-line { white-space: pre-wrap; word-break: break-all; }
    .log-done { color: #58a6ff; margin-top: .25rem; }
    .log-cursor { display: inline-block; color: #58a6ff; animation: blink 1s step-start infinite; }
    @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

    .phase-row { display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; margin-bottom: .5rem; }
    .reassurance {
        margin: 0 0 .5rem;
        padding: .5rem .75rem;
        background: rgba(107,127,77,.12);
        border: 1px solid rgba(107,127,77,.35);
        border-radius: 6px;
        color: var(--text-1);
        font-size: var(--text-sm);
        font-weight: 500;
    }
    .switch-actions { display: flex; gap: .5rem; margin-top: .75rem; flex-wrap: wrap; }

    .region-picker { margin-top: 1rem; padding-top: .75rem; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: .6rem; }
    .quick-picks { display: flex; gap: .4rem; flex-wrap: wrap; }
    .chip-row { display: flex; gap: .4rem; flex-wrap: wrap; }
    .chip {
        display: inline-flex;
        align-items: center;
        gap: .35rem;
        padding: .25rem .5rem;
        background: var(--color-primary);
        color: white;
        border-radius: 4px;
        font-size: var(--text-xs);
    }
    .chip-remove { background: none; border: none; color: white; cursor: pointer; padding: 0; font-size: var(--text-xs); line-height: 1; opacity: .85; }
    .chip-remove:hover { opacity: 1; }
    .overlap-hint {
        margin-bottom: .75rem;
        padding: .5rem .75rem;
        background: rgba(210,120,30,.12);
        border: 1px solid rgba(210,120,30,.35);
        border-radius: 6px;
        font-size: var(--text-sm);
        color: var(--text-1);
    }
    .overlap-hint p { margin: 0 0 .4rem; }
    .overlap-row { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; margin: .25rem 0; }
    .region-search {
        padding: .5rem .75rem;
        border: 1px solid var(--border);
        border-radius: 6px;
        background: var(--surface-2);
        color: var(--text-1);
        font-size: var(--text-sm);
        max-width: var(--admin-field, 34rem);
    }
    .region-search:focus { outline: none; border-color: var(--color-primary); }
    .region-list {
        display: flex;
        flex-direction: column;
        gap: .2rem;
        max-height: 220px;
        overflow-y: auto;
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: .3rem;
    }
    .region-item {
        text-align: left;
        padding: .35rem .5rem;
        border: none;
        border-radius: 4px;
        background: transparent;
        color: var(--text-2);
        font-size: var(--text-sm);
        cursor: pointer;
    }
    .region-item:hover { background: var(--surface-2); }
    .region-item.active { background: var(--color-primary); color: white; }
    .preview-box { padding: .75rem; background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; }
    .preview-title { font-weight: 600; margin-bottom: .5rem; color: var(--text-1); }
</style>
