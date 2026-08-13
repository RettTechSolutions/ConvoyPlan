<script lang="ts">
    /**
     * Admin → Systemübersicht.
     *
     * Drei Ebenen, von oben nach unten: was gerade los ist (Kacheln + Container),
     * wie es sich entwickelt hat (Verlaufsdiagramme über den gewählten Zeitraum)
     * und was im Monat passiert ist (Bericht mit Export).
     *
     * Der Zeitraumfilter steht als einzelne Zeile über allem, was er betrifft,
     * und wirkt auf sämtliche Verlaufsdiagramme gleichzeitig — damit die Kurven
     * untereinander vergleichbar bleiben.
     */
    import { onDestroy, onMount } from 'svelte';
    import MetricChart from './MetricChart.svelte';
    import {
        systemApi,
        type MetricRange,
        type MetricSeries,
        type MonthlyReport,
        type SystemOverview,
        type UsageHistory,
    } from '$lib/api';

    let overview = $state<SystemOverview | null>(null);
    let history = $state<MetricSeries | null>(null);
    let usage = $state<UsageHistory | null>(null);
    let report = $state<MonthlyReport | null>(null);
    let months = $state<string[]>([]);
    let selectedMonth = $state('');

    let range = $state<MetricRange>('24h');
    let loadingOverview = $state(true);
    let loadingHistory = $state(true);
    let loadingReport = $state(false);
    let sampling = $state(false);
    let downloading = $state('');
    let error = $state('');
    let autoRefresh = $state(true);

    const RANGES: { key: MetricRange; label: string }[] = [
        { key: '1h', label: '1 Std.' },
        { key: '6h', label: '6 Std.' },
        { key: '24h', label: '24 Std.' },
        { key: '7d', label: '7 Tage' },
        { key: '30d', label: '30 Tage' },
        { key: '90d', label: '90 Tage' },
        { key: '365d', label: '1 Jahr' },
    ];

    // Ab 7 Tagen trägt die X-Achse Datumsangaben statt Uhrzeiten.
    const dateAxis = $derived(range === '7d' || range === '30d' || range === '90d' || range === '365d');
    const points = $derived(history?.points ?? []);
    const usagePoints = $derived(
        (usage?.days ?? []).map((d) => ({
            t: d.day,
            users: d.users,
            demo_users: d.demo_users,
            admin_users: d.admin_users,
            requests: d.requests,
        })),
    );

    let timer: ReturnType<typeof setInterval> | null = null;

    onMount(async () => {
        await Promise.all([loadOverview(), loadHistory(), loadUsage(), loadMonths()]);
        startTimer();
    });

    onDestroy(() => stopTimer());

    function startTimer() {
        stopTimer();
        // Die Live-Kacheln alle 30 s nachziehen. Der Verlauf bleibt stehen —
        // er ändert sich ohnehin nur im Sampling-Intervall des Collectors.
        timer = setInterval(() => {
            if (autoRefresh) loadOverview();
        }, 30_000);
    }

    function stopTimer() {
        if (timer) clearInterval(timer);
        timer = null;
    }

    function fail(e: unknown, fallback: string) {
        error = e instanceof Error ? e.message : fallback;
    }

    async function loadOverview() {
        try {
            overview = await systemApi.overview();
            error = '';
        } catch (e) {
            fail(e, 'Systemzustand konnte nicht geladen werden');
        } finally {
            loadingOverview = false;
        }
    }

    async function loadHistory() {
        loadingHistory = true;
        try {
            history = await systemApi.history(range);
        } catch (e) {
            fail(e, 'Verlauf konnte nicht geladen werden');
        } finally {
            loadingHistory = false;
        }
    }

    async function loadUsage() {
        try {
            usage = await systemApi.usage(30);
        } catch (e) {
            fail(e, 'Nutzungsdaten konnten nicht geladen werden');
        }
    }

    async function loadMonths() {
        try {
            const data = await systemApi.reportMonths();
            months = data.months;
            selectedMonth = selectedMonth || data.months[0] || data.current;
            await loadReport();
        } catch (e) {
            fail(e, 'Monatsliste konnte nicht geladen werden');
        }
    }

    async function loadReport() {
        if (!selectedMonth) return;
        loadingReport = true;
        try {
            report = await systemApi.monthlyReport(selectedMonth);
        } catch (e) {
            fail(e, 'Monatsbericht konnte nicht geladen werden');
        } finally {
            loadingReport = false;
        }
    }

    async function selectRange(next: MetricRange) {
        range = next;
        await loadHistory();
    }

    async function sampleNow() {
        sampling = true;
        try {
            await systemApi.sampleNow();
            await Promise.all([loadOverview(), loadHistory()]);
        } catch (e) {
            fail(e, 'Messung fehlgeschlagen');
        } finally {
            sampling = false;
        }
    }

    async function download(format: 'csv' | 'pdf') {
        if (!selectedMonth) return;
        downloading = format;
        try {
            await systemApi.downloadReport(selectedMonth, format);
        } catch (e) {
            fail(e, 'Download fehlgeschlagen');
        } finally {
            downloading = '';
        }
    }

    async function downloadHistory() {
        downloading = 'history';
        try {
            await systemApi.downloadHistoryCsv(range);
        } catch (e) {
            fail(e, 'Download fehlgeschlagen');
        } finally {
            downloading = '';
        }
    }

    // ── Formatierung ─────────────────────────────────────────────────────────

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

    function percent(value: number | null | undefined, decimals = 1): string {
        if (value == null) return '–';
        return `${value.toFixed(decimals).replace('.', ',')} %`;
    }

    function num(value: number | null | undefined): string {
        if (value == null) return '–';
        return value.toLocaleString('de-DE');
    }

    function duration(seconds: number | null | undefined): string {
        if (seconds == null) return '–';
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        if (days) return `${days} T ${hours} Std.`;
        if (hours) return `${hours} Std. ${minutes} Min.`;
        return `${minutes} Min.`;
    }

    function time(iso: string | null | undefined): string {
        if (!iso) return '–';
        const date = new Date(iso);
        return Number.isNaN(date.getTime()) ? '–' : date.toLocaleString('de-DE');
    }

    function monthLabel(month: string): string {
        const names = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
            'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];
        const [year, mon] = month.split('-');
        const index = Number(mon) - 1;
        return names[index] ? `${names[index]} ${year}` : month;
    }

    /** Ampelstufe einer Auslastung. Immer zusammen mit dem Zahlenwert und einem
     *  Wort ausgegeben — die Farbe allein trägt nie die Aussage. */
    function level(value: number | null | undefined, warn = 70, serious = 85, critical = 95): string {
        if (value == null) return 'unknown';
        if (value >= critical) return 'critical';
        if (value >= serious) return 'serious';
        if (value >= warn) return 'warning';
        return 'good';
    }

    const LEVEL_WORDS: Record<string, string> = {
        good: 'normal',
        warning: 'erhöht',
        serious: 'hoch',
        critical: 'kritisch',
        unknown: 'unbekannt',
    };

    /** Druck (PSI) hat eine ganz andere Skala als Auslastung: alles über ~10 %
     *  Wartezeit ist bereits spürbar, über 40 % ist die Ressource der Engpass. */
    function pressureLevel(value: number | null | undefined): string {
        return level(value, 10, 25, 40);
    }

    function containerLevel(state: string, health: string | null): string {
        if (health === 'unhealthy' || ['exited', 'dead', 'restarting'].includes(state)) return 'critical';
        if (health === 'starting' || state === 'created' || state === 'paused') return 'warning';
        return 'good';
    }

    function containerWord(state: string, health: string | null): string {
        if (health === 'unhealthy') return 'ungesund';
        if (health === 'healthy') return 'gesund';
        if (health === 'starting') return 'startet';
        const words: Record<string, string> = {
            running: 'läuft',
            exited: 'beendet',
            restarting: 'startet neu',
            dead: 'tot',
            paused: 'pausiert',
            created: 'erstellt',
        };
        return words[state] ?? state;
    }
</script>

<div class="sysview">
    {#if error}
        <div class="error-bar">{error} <button onclick={() => (error = '')}>✕</button></div>
    {/if}

    <!-- ── Live-Zustand ─────────────────────────────────────────────────── -->
    <div class="section">
        <div class="section-header">
            <strong>Aktueller Zustand</strong>
            <div class="head-actions">
                <label class="auto-toggle">
                    <input type="checkbox" bind:checked={autoRefresh} />
                    Auto (30 s)
                </label>
                <button class="btn-small" onclick={loadOverview} disabled={loadingOverview}>↺</button>
                <button class="btn-small" onclick={sampleNow} disabled={sampling}>
                    {sampling ? '…' : 'Jetzt messen'}
                </button>
            </div>
        </div>

        {#if loadingOverview && !overview}
            <p class="hint">Lade…</p>
        {:else if overview}
            <div class="tiles">
                <div class="tile">
                    <span class="tile-label">CPU</span>
                    <span class="tile-value">{percent(overview.host.cpu_percent)}</span>
                    <div class="meter" aria-hidden="true">
                        <span
                            class={`meter-fill lvl-${level(overview.host.cpu_percent)}`}
                            style={`width: ${Math.min(100, overview.host.cpu_percent ?? 0)}%`}
                        ></span>
                    </div>
                    <span class="tile-sub">
                        {overview.host.cpu_count ?? '–'} Kerne · Last {overview.host.load1 ?? '–'} /
                        {overview.host.load5 ?? '–'} / {overview.host.load15 ?? '–'}
                    </span>
                </div>

                <div class="tile">
                    <span class="tile-label">Arbeitsspeicher</span>
                    <span class="tile-value">{percent(overview.host.mem_percent)}</span>
                    <div class="meter" aria-hidden="true">
                        <span
                            class={`meter-fill lvl-${level(overview.host.mem_percent)}`}
                            style={`width: ${Math.min(100, overview.host.mem_percent ?? 0)}%`}
                        ></span>
                    </div>
                    <span class="tile-sub">
                        {bytes(overview.host.mem_used_bytes)} von {bytes(overview.host.mem_total_bytes)}
                        {#if overview.host.swap_total_bytes}
                            · Swap {bytes(overview.host.swap_used_bytes)}
                        {/if}
                    </span>
                </div>

                <div class="tile">
                    <span class="tile-label">Massenspeicher</span>
                    <span class="tile-value">{percent(overview.host.disk_percent)}</span>
                    <div class="meter" aria-hidden="true">
                        <span
                            class={`meter-fill lvl-${level(overview.host.disk_percent, 75, 85, 92)}`}
                            style={`width: ${Math.min(100, overview.host.disk_percent ?? 0)}%`}
                        ></span>
                    </div>
                    <span class="tile-sub">
                        {bytes(overview.host.disk_used_bytes)} von {bytes(overview.host.disk_total_bytes)} belegt
                    </span>
                </div>

                <div class="tile">
                    <span class="tile-label">Plattendruck (I/O)</span>
                    <span class="tile-value">
                        {overview.host.psi_io_avg10 == null ? 'n. v.' : percent(overview.host.psi_io_avg10, 2)}
                    </span>
                    <div class="meter" aria-hidden="true">
                        <span
                            class={`meter-fill lvl-${pressureLevel(overview.host.psi_io_avg10)}`}
                            style={`width: ${Math.min(100, (overview.host.psi_io_avg10 ?? 0) * 2)}%`}
                        ></span>
                    </div>
                    <span class="tile-sub">
                        {#if overview.host.psi_io_avg10 == null}
                            Kernel liefert keine PSI-Werte
                        {:else}
                            ↓ {bytes(overview.host.disk_read_bytes_s)}/s · ↑ {bytes(overview.host.disk_write_bytes_s)}/s
                        {/if}
                    </span>
                </div>

                <div class="tile">
                    <span class="tile-label">Benutzer im Portal</span>
                    <span class="tile-value">{num(overview.usage.active_users)}</span>
                    <span class="tile-sub">
                        gerade aktiv ({Math.round(overview.usage.window_seconds / 60)} Min.-Fenster)
                        · heute {num(overview.usage.unique_users_today)} · Anmeldungen 24 h
                        {num(overview.usage.logins_24h)}
                    </span>
                    <span class="tile-sub">
                        dazu {num(overview.usage.active_demo_users)} Demo
                        ({num(overview.usage.unique_demo_users_today)} heute)
                        · {num(overview.usage.active_admin_users)} Admin
                    </span>
                </div>

                <div class="tile">
                    <span class="tile-label">Container</span>
                    {#if overview.docker.available}
                        <span class="tile-value">
                            {overview.docker.running} / {overview.docker.total}
                        </span>
                        <span class={`badge lvl-${overview.docker.unhealthy > 0 ? 'critical' : 'good'}`}>
                            {overview.docker.unhealthy > 0
                                ? `${overview.docker.unhealthy} auffällig`
                                : 'alle gesund'}
                        </span>
                        <span class="tile-sub">Docker {overview.docker.engine_version ?? ''}</span>
                    {:else}
                        <span class="tile-value">n. v.</span>
                        <span class="tile-sub">{overview.docker.reason ?? 'Docker-API nicht erreichbar'}</span>
                    {/if}
                </div>

                <div class="tile">
                    <span class="tile-label">Datenbank</span>
                    <span class="tile-value">{bytes(overview.database.size_bytes)}</span>
                    <span class="tile-sub">
                        {num(overview.database.connections)} Verbindungen ·
                        {num(overview.database.users)} Benutzer ·
                        {num(overview.database.organizations)} Orgs ·
                        {num(overview.database.convoys)} Kolonnen
                    </span>
                </div>

                <div class="tile">
                    <span class="tile-label">Laufzeit &amp; Erfassung</span>
                    <span class="tile-value">{duration(overview.host.uptime_seconds)}</span>
                    <span class="tile-sub">
                        Host-Laufzeit · letzte Messung {time(overview.collector.last_sample_at)}
                        · alle {Math.round(overview.collector.interval_s / 60)} Min.
                    </span>
                </div>
            </div>

            {#if overview.host.disks.length > 1}
                <div class="disk-list">
                    {#each overview.host.disks as disk}
                        <div class="disk-row">
                            <code class="disk-path">{disk.path}</code>
                            <div class="meter" aria-hidden="true">
                                <span
                                    class={`meter-fill lvl-${level(disk.percent, 75, 85, 92)}`}
                                    style={`width: ${Math.min(100, disk.percent)}%`}
                                ></span>
                            </div>
                            <span class="disk-figures">
                                {percent(disk.percent)} · {bytes(disk.free_bytes)} frei von {bytes(disk.total_bytes)}
                            </span>
                        </div>
                    {/each}
                </div>
            {/if}
        {/if}
    </div>

    <!-- ── Container ────────────────────────────────────────────────────── -->
    {#if overview?.docker.available}
        <div class="section">
            <div class="section-header"><strong>Container ({overview.docker.total})</strong></div>
            <table class="user-table">
                <thead>
                    <tr>
                        <th>Dienst</th>
                        <th>Zustand</th>
                        <th>Status</th>
                        <th>CPU</th>
                        <th>RAM</th>
                    </tr>
                </thead>
                <tbody>
                    {#each overview.docker.containers as container}
                        <tr>
                            <td><strong>{container.name}</strong></td>
                            <td>
                                <span class={`badge lvl-${containerLevel(container.state, container.health)}`}>
                                    {containerWord(container.state, container.health)}
                                </span>
                            </td>
                            <td class="status-cell">{container.status}</td>
                            <td>{container.cpu_percent == null ? '–' : percent(container.cpu_percent)}</td>
                            <td>
                                {bytes(container.mem_bytes)}
                                {#if container.mem_percent != null}
                                    <span class="hint-inline">({percent(container.mem_percent, 0)})</span>
                                {/if}
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </div>
    {/if}

    <!-- ── Verlauf ──────────────────────────────────────────────────────── -->
    <div class="section">
        <div class="section-header">
            <strong>Verlauf</strong>
            <div class="head-actions">
                <span class="hint-inline">
                    {#if history}
                        {history.points.length} Punkte ·
                        {history.resolution === 'raw' ? 'Rohdaten' : history.resolution === 'hour' ? 'Stundenmittel' : 'Tageswerte'}
                    {/if}
                </span>
                <button class="btn-small" onclick={downloadHistory} disabled={downloading === 'history'}>
                    {downloading === 'history' ? '…' : 'CSV'}
                </button>
            </div>
        </div>

        <!-- Zeitraumfilter: eine Zeile, gilt für alle Diagramme darunter. -->
        <div class="range-row">
            {#each RANGES as r}
                <button
                    class="range-btn"
                    class:active={range === r.key}
                    onclick={() => selectRange(r.key)}
                    disabled={loadingHistory}
                >{r.label}</button>
            {/each}
        </div>

        <div class="charts" class:reloading={loadingHistory}>
            <MetricChart
                title="CPU-Auslastung"
                {points}
                series={[{ key: 'cpu_percent', label: 'CPU' }]}
                unit="%"
                yMax={100}
                {dateAxis}
            />
            <MetricChart
                title="Arbeitsspeicher"
                {points}
                series={[{ key: 'mem_percent', label: 'Belegt' }]}
                unit="%"
                yMax={100}
                {dateAxis}
            />
            <MetricChart
                title="Plattenbelegung"
                {points}
                series={[{ key: 'disk_percent', label: 'Belegt' }]}
                unit="%"
                yMax={100}
                {dateAxis}
            />
            <MetricChart
                title="Druck auf Platte, CPU und Speicher (PSI)"
                {points}
                series={[
                    { key: 'psi_io_avg10', label: 'I/O' },
                    { key: 'psi_cpu_avg10', label: 'CPU' },
                    { key: 'psi_mem_avg10', label: 'Speicher' },
                ]}
                unit="%"
                decimals={2}
                {dateAxis}
                empty="Der Kernel dieses Hosts liefert keine PSI-Werte (benötigt Linux 4.20+)."
            />
            <MetricChart
                title="Platten-Durchsatz"
                {points}
                series={[
                    { key: 'disk_read_bytes_s', label: 'Lesen' },
                    { key: 'disk_write_bytes_s', label: 'Schreiben' },
                ]}
                format="bytes"
                unit="s"
                {dateAxis}
            />
            <MetricChart
                title="Benutzer im Portal"
                {points}
                series={[
                    { key: 'active_users', label: 'Gleichzeitig aktiv' },
                    { key: 'active_demo_users', label: 'davon Demo' },
                ]}
                decimals={0}
                {dateAxis}
            />
            <MetricChart
                title="Requests und Serverfehler"
                {points}
                series={[
                    { key: 'requests', label: 'Requests' },
                    { key: 'request_errors', label: 'Fehler (5xx)' },
                ]}
                decimals={0}
                {dateAxis}
            />
            <MetricChart
                title="Datenbankgröße"
                {points}
                series={[{ key: 'db_size_bytes', label: 'Größe' }]}
                format="bytes"
                {dateAxis}
            />
        </div>
    </div>

    <!-- ── Nutzung je Tag ───────────────────────────────────────────────── -->
    <div class="section">
        <div class="section-header">
            <strong>Portalnutzung (30 Tage)</strong>
            {#if usage}
                <span class="hint-inline">
                    {usage.unique_users} eindeutige Benutzer im Zeitraum
                    · {usage.unique_demo_users} Demo · {usage.unique_admin_users} Admin
                </span>
            {/if}
        </div>
        <MetricChart
            title="Eindeutige Benutzer je Tag"
            points={usagePoints}
            series={[
                { key: 'users', label: 'Portalnutzer' },
                { key: 'demo_users', label: 'Demo-Besucher' },
                { key: 'admin_users', label: 'Administration' },
            ]}
            decimals={0}
            dateAxis={true}
            empty="Noch keine Nutzungsdaten — sie entstehen, sobald sich Benutzer anmelden."
        />
        <p class="hint">
            Demo-Sitzungen bekommen je Aufruf ein eigenes Wegwerfkonto und Superadmins arbeiten
            im Admin-Portal — beides zählt getrennt, damit „Portalnutzer" die tatsächliche
            Nutzung der Organisationen zeigt.
        </p>
    </div>

    <!-- ── Monatsbericht ────────────────────────────────────────────────── -->
    <div class="section">
        <div class="section-header">
            <strong>Monatsbericht</strong>
            <div class="head-actions">
                <!-- Kein bind:value — der Wert wird im Handler gesetzt, damit
                     loadReport() garantiert den neu gewählten Monat sieht. -->
                <select
                    value={selectedMonth}
                    onchange={(e) => {
                        selectedMonth = (e.currentTarget as HTMLSelectElement).value;
                        loadReport();
                    }}
                    class="month-select"
                >
                    {#each months as month}
                        <option value={month}>{monthLabel(month)}</option>
                    {/each}
                </select>
                <button class="btn-small" onclick={() => download('csv')} disabled={downloading === 'csv'}>
                    {downloading === 'csv' ? '…' : 'CSV'}
                </button>
                <button class="btn-small" onclick={() => download('pdf')} disabled={downloading === 'pdf'}>
                    {downloading === 'pdf' ? '…' : 'PDF'}
                </button>
            </div>
        </div>

        {#if loadingReport}
            <p class="hint">Lade…</p>
        {:else if report && report.days_covered > 0}
            <div class="report-grid">
                <div class="report-item">
                    <span class="report-label">Eindeutige Benutzer</span>
                    <span class="report-value">{num(report.summary.unique_users as number)}</span>
                </div>
                <div class="report-item">
                    <span class="report-label">Demo-Besucher</span>
                    <span class="report-value">{num(report.summary.unique_demo_users as number)}</span>
                </div>
                <div class="report-item">
                    <span class="report-label">Gleichzeitig aktiv (Spitze)</span>
                    <span class="report-value">{num(report.summary.active_users_max as number)}</span>
                </div>
                <div class="report-item">
                    <span class="report-label">Anmeldungen</span>
                    <span class="report-value">{num(report.summary.logins as number)}</span>
                </div>
                <div class="report-item">
                    <span class="report-label">Requests</span>
                    <span class="report-value">{num(report.summary.requests as number)}</span>
                </div>
                <div class="report-item">
                    <span class="report-label">Serverfehler</span>
                    <span class="report-value">{num(report.summary.request_errors as number)}</span>
                </div>
                <div class="report-item">
                    <span class="report-label">CPU Ø / Spitze</span>
                    <span class="report-value">
                        {percent(report.summary.cpu_percent_avg as number)} / {percent(report.summary.cpu_percent_max as number)}
                    </span>
                </div>
                <div class="report-item">
                    <span class="report-label">RAM Ø / Spitze</span>
                    <span class="report-value">
                        {percent(report.summary.mem_percent_avg as number)} / {percent(report.summary.mem_percent_max as number)}
                    </span>
                </div>
                <div class="report-item">
                    <span class="report-label">Platte Ø / Spitze</span>
                    <span class="report-value">
                        {percent(report.summary.disk_percent_avg as number)} / {percent(report.summary.disk_percent_max as number)}
                    </span>
                </div>
                <div class="report-item">
                    <span class="report-label">Plattenwachstum</span>
                    <span class="report-value">
                        {bytes(report.summary.disk_used_start_bytes as number)} → {bytes(report.summary.disk_used_end_bytes as number)}
                    </span>
                </div>
                <div class="report-item">
                    <span class="report-label">Datenbank</span>
                    <span class="report-value">
                        {bytes(report.summary.db_size_start_bytes as number)} → {bytes(report.summary.db_size_end_bytes as number)}
                    </span>
                </div>
                <div class="report-item">
                    <span class="report-label">I/O-Druck Ø / Spitze</span>
                    <span class="report-value">
                        {percent(report.summary.psi_io_avg as number, 2)} / {percent(report.summary.psi_io_max as number, 2)}
                    </span>
                </div>
                <div class="report-item">
                    <span class="report-label">Tage mit Container-Störung</span>
                    <span class="report-value">{num(report.summary.days_with_unhealthy_containers as number)}</span>
                </div>
            </div>
            <p class="hint">
                {report.days_covered} erfasste Tage · stärkster Tag:
                {report.summary.busiest_day ?? '–'}
                ({num(report.summary.busiest_day_users as number)} Benutzer)
            </p>
        {:else}
            <p class="hint">
                Für {monthLabel(selectedMonth)} liegen noch keine verdichteten Tageswerte vor.
                Tageswerte entstehen jeweils nach Mitternacht aus den Stichproben.
            </p>
        {/if}
    </div>
</div>

<style>
    /* Statusfarben — fest, nie umgefärbt, und immer zusammen mit einem Wort
       oder Zahlenwert verwendet, damit die Aussage nie an der Farbe allein hängt. */
    .sysview {
        --lvl-good: #0ca30c;
        --lvl-warning: #fab219;
        --lvl-serious: #ec835a;
        --lvl-critical: #d03b3b;
        --lvl-unknown: var(--text-muted);
    }

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
        gap: .75rem;
        margin-bottom: .75rem;
        font-size: var(--text-sm);
        color: var(--text-1);
        flex-wrap: wrap;
    }
    .head-actions { display: flex; align-items: center; gap: .4rem; flex-wrap: wrap; }
    .auto-toggle {
        display: inline-flex;
        align-items: center;
        gap: .3rem;
        font-size: var(--text-xs);
        color: var(--text-2);
        cursor: pointer;
    }
    .btn-small {
        padding: .25rem .55rem;
        border-radius: 4px;
        border: 1px solid var(--border);
        background: var(--surface-2);
        color: var(--text-2);
        font-size: var(--text-xs);
        cursor: pointer;
    }
    .btn-small:hover:not(:disabled) { color: var(--color-primary); border-color: var(--color-primary); }
    .btn-small:disabled { opacity: .5; cursor: not-allowed; }
    .month-select {
        padding: .25rem .4rem;
        border-radius: 4px;
        border: 1px solid var(--border);
        background: var(--surface-2);
        color: var(--text-1);
        font-size: var(--text-xs);
    }

    .hint { font-size: var(--text-sm); color: var(--text-2); margin: .5rem 0 0; }
    .hint-inline { font-size: var(--text-xs); color: var(--text-muted); }
    .error-bar {
        background: var(--color-primary-hover);
        color: white;
        padding: .4rem .75rem;
        border-radius: 4px;
        margin-bottom: 1rem;
        display: flex;
        justify-content: space-between;
    }
    .error-bar button { background: none; border: none; color: white; cursor: pointer; }

    /* ── Kacheln ── */
    .tiles {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
        gap: .6rem;
    }
    .tile {
        display: flex;
        flex-direction: column;
        gap: .2rem;
        padding: .6rem .7rem;
        background: var(--surface-2);
        border: 1px solid var(--border);
        border-radius: 8px;
    }
    .tile-label {
        font-size: var(--text-xs);
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: .04em;
    }
    .tile-value { font-size: 1.4rem; font-weight: 700; color: var(--text-1); line-height: 1.15; }
    .tile-sub { font-size: var(--text-xs); color: var(--text-2); line-height: 1.35; }

    .meter {
        height: 6px;
        border-radius: 3px;
        background: color-mix(in srgb, var(--text-muted) 25%, transparent);
        overflow: hidden;
        margin: .15rem 0;
    }
    .meter-fill { display: block; height: 100%; border-radius: 3px; }
    .meter-fill.lvl-good { background: var(--lvl-good); }
    .meter-fill.lvl-warning { background: var(--lvl-warning); }
    .meter-fill.lvl-serious { background: var(--lvl-serious); }
    .meter-fill.lvl-critical { background: var(--lvl-critical); }
    .meter-fill.lvl-unknown { background: var(--lvl-unknown); }

    .badge {
        display: inline-block;
        align-self: flex-start;
        padding: .1rem .4rem;
        border-radius: 3px;
        font-size: var(--text-xs);
        font-weight: 600;
        border: 1px solid;
    }
    .badge.lvl-good { color: var(--lvl-good); border-color: color-mix(in srgb, var(--lvl-good) 45%, transparent); background: color-mix(in srgb, var(--lvl-good) 12%, transparent); }
    .badge.lvl-warning { color: #a06f00; border-color: color-mix(in srgb, var(--lvl-warning) 55%, transparent); background: color-mix(in srgb, var(--lvl-warning) 16%, transparent); }
    .badge.lvl-serious { color: #b0522a; border-color: color-mix(in srgb, var(--lvl-serious) 55%, transparent); background: color-mix(in srgb, var(--lvl-serious) 16%, transparent); }
    .badge.lvl-critical { color: var(--lvl-critical); border-color: color-mix(in srgb, var(--lvl-critical) 45%, transparent); background: color-mix(in srgb, var(--lvl-critical) 12%, transparent); }
    :global([data-theme='dark']) .badge.lvl-warning { color: var(--lvl-warning); }
    :global([data-theme='dark']) .badge.lvl-serious { color: var(--lvl-serious); }

    /* ── Datenträgerliste ── */
    .disk-list { display: flex; flex-direction: column; gap: .35rem; margin-top: .75rem; }
    .disk-row { display: grid; grid-template-columns: 9rem 1fr auto; gap: .6rem; align-items: center; }
    .disk-path { font-size: var(--text-xs); color: var(--text-2); overflow-wrap: anywhere; }
    .disk-figures { font-size: var(--text-xs); color: var(--text-2); white-space: nowrap; }

    /* ── Tabellen ── */
    .user-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
    .user-table th {
        text-align: left;
        padding: .5rem;
        color: var(--text-muted);
        font-size: var(--text-xs);
        text-transform: uppercase;
        letter-spacing: .04em;
        border-bottom: 1px solid var(--border);
    }
    .user-table td { padding: .5rem; border-bottom: 1px solid var(--border); color: var(--text-2); }
    .status-cell { color: var(--text-muted); font-size: var(--text-xs); }

    /* ── Diagramme ── */
    .range-row { display: flex; flex-wrap: wrap; gap: .3rem; margin-bottom: .75rem; }
    .range-btn {
        padding: .25rem .6rem;
        border-radius: 999px;
        border: 1px solid var(--border);
        background: var(--surface-2);
        color: var(--text-2);
        font-size: var(--text-xs);
        cursor: pointer;
    }
    .range-btn.active {
        border-color: var(--color-primary);
        color: var(--color-primary);
        font-weight: 600;
    }
    .range-btn:disabled { opacity: .6; cursor: progress; }

    .charts {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));
        gap: .6rem;
        transition: opacity .15s ease;
    }
    /* Beim Nachladen bleibt die vorherige Zeichnung stehen (nur abgeblendet) —
       kein Skelett, kein Springen des Layouts. */
    .charts.reloading { opacity: .55; }

    /* ── Monatsbericht ── */
    .report-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(13rem, 1fr));
        gap: .5rem;
    }
    .report-item {
        display: flex;
        flex-direction: column;
        gap: .1rem;
        padding: .5rem .6rem;
        background: var(--surface-2);
        border: 1px solid var(--border);
        border-radius: 6px;
    }
    .report-label { font-size: var(--text-xs); color: var(--text-muted); }
    .report-value { font-size: var(--text-base); font-weight: 600; color: var(--text-1); }

    @media (max-width: 640px) {
        .charts { grid-template-columns: 1fr; }
        .disk-row { grid-template-columns: 1fr; gap: .2rem; }
    }
</style>
