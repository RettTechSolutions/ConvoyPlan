<script lang="ts">
    /**
     * Verlaufsdiagramm für die Systemübersicht.
     *
     * Bewusst handgezeichnetes SVG statt einer Chart-Bibliothek: gebraucht wird
     * genau eine Form (Zeitreihe als Linie/Fläche), und das Frontend-Bundle
     * bleibt frei von einer weiteren Abhängigkeit.
     *
     * Gestaltung nach den Hausregeln für Diagramme: 2 px Linien, Flächen als
     * 10-%-Wash, hauchdünnes Raster, Legende ab zwei Reihen, Direktbeschriftung
     * am Reihenende, Fadenkreuz-Tooltip — und eine Tabellenansicht, damit jeder
     * Wert auch ohne Hover und ohne Farbunterscheidung erreichbar ist.
     */
    import type { MetricPoint } from '$lib/api';

    /** Eine dargestellte Reihe: Feldname im Datenpunkt plus Beschriftung. */
    type ChartSeries = { key: string; label: string };

    let {
        points = [],
        series = [],
        height = 190,
        unit = '',
        yMax = null,
        title = '',
        /** Zeitstempel als Datum statt Uhrzeit beschriften (Zeiträume > 2 Tage) */
        dateAxis = false,
        decimals = 1,
        /** 'bytes' formatiert Achse und Werte als KB/MB/GB statt als rohe Zahl. */
        format = 'number',
        empty = 'Noch keine Messwerte für diesen Zeitraum.',
    }: {
        points?: MetricPoint[];
        series?: ChartSeries[];
        height?: number;
        unit?: string;
        yMax?: number | null;
        title?: string;
        dateAxis?: boolean;
        decimals?: number;
        format?: 'number' | 'bytes';
        empty?: string;
    } = $props();

    let width = $state(640);
    let hoverIndex = $state<number | null>(null);
    let showTable = $state(false);

    // Platz für Achsenbeschriftung links, Direktlabel rechts, Ticks unten.
    const PAD = { top: 12, right: 58, bottom: 22, left: 44 };

    const plotWidth = $derived(Math.max(40, width - PAD.left - PAD.right));
    const plotHeight = $derived(Math.max(30, height - PAD.top - PAD.bottom));

    const values = $derived(
        series.map((s) =>
            points.map((p) => {
                const raw = p[s.key];
                return typeof raw === 'number' && Number.isFinite(raw) ? raw : null;
            }),
        ),
    );

    /** Schrittweite, die auf einer runden Zahl landet (1, 2, 2,5 oder 5 mal
     *  Zehnerpotenz). Ohne das stünde an der Achse „3,8" statt „4".
     *
     *  Bei Byte-Achsen wird stattdessen in Vielfachen von 1024 gerundet, damit
     *  die Beschriftung „1 GB / 2 GB / 3 GB" lautet und nicht „954 MB / 1,9 GB". */
    function niceStep(rough: number): number {
        if (rough <= 0) return 1;
        const base = format === 'bytes' ? 1024 : 10;
        const magnitude = base ** Math.floor(Math.log(rough) / Math.log(base));
        const normalized = rough / magnitude;
        const candidates = format === 'bytes'
            ? [1, 2, 5, 10, 25, 50, 100, 250, 500, 1024]
            : [1, 2, 2.5, 5, 10];
        const stepped = candidates.find((c) => normalized <= c) ?? candidates[candidates.length - 1];
        return stepped * magnitude;
    }

    const TICK_COUNT = 4;

    const scale = $derived.by(() => {
        if (yMax != null) return { max: yMax, step: yMax / TICK_COUNT };
        const all = values.flat().filter((v): v is number => v != null);
        const peak = all.length ? Math.max(...all) : 0;
        if (peak <= 0) return { max: 1, step: 0.25 };
        const step = niceStep(peak / TICK_COUNT);
        return { max: Math.ceil(peak / step) * step, step };
    });

    const maxValue = $derived(scale.max);

    const ticks = $derived.by(() => {
        const out: number[] = [];
        for (let value = 0; value <= maxValue + scale.step / 2; value += scale.step) out.push(value);
        return out;
    });

    function x(index: number): number {
        if (points.length <= 1) return PAD.left + plotWidth / 2;
        return PAD.left + (index / (points.length - 1)) * plotWidth;
    }

    function y(value: number): number {
        const clamped = Math.max(0, Math.min(maxValue, value));
        return PAD.top + plotHeight - (clamped / maxValue) * plotHeight;
    }

    /** Pfad einer Reihe. Lücken (null) unterbrechen die Linie, statt sie quer
     *  durch das Diagramm zu ziehen — ein Ausfall soll als Ausfall sichtbar sein. */
    function linePath(vals: (number | null)[]): string {
        let path = '';
        let penDown = false;
        vals.forEach((v, i) => {
            if (v == null) {
                penDown = false;
                return;
            }
            path += `${penDown ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)} `;
            penDown = true;
        });
        return path.trim();
    }

    /** Fläche unter der Linie — nur bei einer einzelnen Reihe, sonst überlagern
     *  sich die Waschungen und niemand erkennt mehr, was oben liegt. */
    function areaPath(vals: (number | null)[]): string {
        const baseline = PAD.top + plotHeight;
        let path = '';
        let segmentStart = -1;
        const closeSegment = (endIndex: number) => {
            if (segmentStart < 0) return;
            path += `L${x(endIndex).toFixed(1)} ${baseline.toFixed(1)} L${x(segmentStart).toFixed(1)} ${baseline.toFixed(1)} Z `;
            segmentStart = -1;
        };
        vals.forEach((v, i) => {
            if (v == null) {
                closeSegment(i - 1);
                return;
            }
            if (segmentStart < 0) {
                segmentStart = i;
                path += `M${x(i).toFixed(1)} ${y(v).toFixed(1)} `;
            } else {
                path += `L${x(i).toFixed(1)} ${y(v).toFixed(1)} `;
            }
        });
        closeSegment(vals.length - 1);
        return path.trim();
    }

    /** Letzter belegter Punkt einer Reihe — Anker für Endpunkt und Direktlabel. */
    function lastPoint(vals: (number | null)[]): { index: number; value: number } | null {
        for (let i = vals.length - 1; i >= 0; i--) {
            const v = vals[i];
            if (v != null) return { index: i, value: v };
        }
        return null;
    }

    /** Endpunkte samt Position der Direktbeschriftung.
     *
     *  Liegen zwei Reihen am Ende dicht beieinander, würden sich ihre Labels
     *  überlagern und beide unlesbar machen — deshalb werden sie hier von oben
     *  nach unten auf Mindestabstand geschoben. Der Punkt selbst bleibt, wo er
     *  ist; nur die Schrift weicht aus. */
    const LABEL_MIN_GAP = 11;

    type EndMarker = { slot: number; index: number; value: number; y: number; labelY: number };

    const endMarkers = $derived.by(() => {
        const markers: EndMarker[] = [];
        series.forEach((_s, i) => {
            const last = lastPoint(values[i]);
            if (!last) return;
            const dotY = y(last.value);
            markers.push({ slot: i + 1, index: last.index, value: last.value, y: dotY, labelY: dotY });
        });

        const ordered = [...markers].sort((a, b) => a.y - b.y);
        let previous = -Infinity;
        for (const marker of ordered) {
            marker.labelY = Math.max(marker.y, previous + LABEL_MIN_GAP);
            previous = marker.labelY;
        }
        // Ist die Gruppe unten aus der Zeichenfläche gelaufen, komplett nach
        // oben schieben, statt die letzte Beschriftung in die Zeitachse zu
        // setzen. Der Abstand untereinander bleibt dabei erhalten.
        const overflow = previous - (PAD.top + plotHeight);
        if (overflow > 0) {
            for (const marker of ordered) marker.labelY -= overflow;
        }
        return markers;
    });

    /** Bytes menschenlesbar — für Durchsatz und Größenangaben. */
    function formatBytes(value: number, digits = 1): string {
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        let size = value;
        let unitIndex = 0;
        while (Math.abs(size) >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex++;
        }
        return `${size.toFixed(unitIndex === 0 ? 0 : digits).replace('.', ',')} ${units[unitIndex]}`;
    }

    function formatValue(value: number | null): string {
        if (value == null) return '–';
        if (format === 'bytes') return `${formatBytes(value)}${unit ? `/${unit}` : ''}`;
        const fixed = value.toFixed(decimals);
        return `${fixed.replace('.', ',')}${unit ? ` ${unit}` : ''}`;
    }

    /** Achsenbeschriftung: kurz halten, ohne die Größenordnung zu verlieren. */
    function formatTick(value: number): string {
        if (format === 'bytes') return formatBytes(value, 0);
        if (maxValue >= 1_000_000) return `${(value / 1_000_000).toFixed(value % 1_000_000 ? 1 : 0).replace('.', ',')} M`;
        if (maxValue >= 10_000) return `${(value / 1000).toFixed(value % 1000 ? 1 : 0).replace('.', ',')} k`;
        if (Number.isInteger(value)) return String(value);
        return value.toFixed(value < 1 ? 2 : 1).replace('.', ',');
    }

    function formatTime(iso: string): string {
        const date = new Date(iso);
        if (Number.isNaN(date.getTime())) return iso;
        return dateAxis
            ? date.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })
            : date.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
    }

    function formatFull(iso: string): string {
        const date = new Date(iso);
        if (Number.isNaN(date.getTime())) return iso;
        return date.toLocaleString('de-DE', {
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit',
        });
    }

    /** Beschriftete X-Positionen: höchstens sechs, gleichmäßig verteilt. */
    const xLabels = $derived.by(() => {
        if (!points.length) return [] as { index: number; label: string }[];
        const count = Math.min(6, points.length);
        const step = Math.max(1, Math.floor((points.length - 1) / Math.max(1, count - 1)));
        const out: { index: number; label: string }[] = [];
        for (let i = 0; i < points.length; i += step) {
            out.push({ index: i, label: formatTime(String(points[i].t)) });
        }
        return out;
    });

    function onPointerMove(event: PointerEvent) {
        const target = event.currentTarget as SVGSVGElement;
        const rect = target.getBoundingClientRect();
        const relative = event.clientX - rect.left - PAD.left;
        if (!points.length) return;
        const ratio = plotWidth > 0 ? relative / plotWidth : 0;
        hoverIndex = Math.max(0, Math.min(points.length - 1, Math.round(ratio * (points.length - 1))));
    }

    /** Tooltip nach links kippen, sobald der Zeiger die rechte Hälfte erreicht,
     *  damit die Karte nicht über den Diagrammrand hinausragt. */
    const tooltipFlipped = $derived(hoverIndex != null && x(hoverIndex) > PAD.left + plotWidth * 0.6);
</script>

<div class="chart-card">
    <div class="chart-head">
        <span class="chart-title">{title}</span>
        <button
            type="button"
            class="table-toggle"
            aria-pressed={showTable}
            onclick={() => (showTable = !showTable)}
        >{showTable ? 'Diagramm' : 'Tabelle'}</button>
    </div>

    {#if series.length > 1}
        <div class="legend">
            {#each series as s, i}
                <span class="legend-item">
                    <span class="legend-key" style={`background: var(--series-${i + 1})`}></span>
                    {s.label}
                </span>
            {/each}
        </div>
    {/if}

    {#if !points.length}
        <p class="chart-empty">{empty}</p>
    {:else if showTable}
        <div class="table-wrap">
            <table class="chart-table">
                <thead>
                    <tr>
                        <th>Zeitpunkt</th>
                        {#each series as s}<th>{s.label}</th>{/each}
                    </tr>
                </thead>
                <tbody>
                    {#each points as point, i}
                        <tr>
                            <td>{formatFull(String(point.t))}</td>
                            {#each series as _s, si}<td>{formatValue(values[si][i])}</td>{/each}
                        </tr>
                    {/each}
                </tbody>
            </table>
        </div>
    {:else}
        <div class="plot" bind:clientWidth={width}>
            <svg
                {height}
                width="100%"
                viewBox={`0 0 ${width} ${height}`}
                role="img"
                aria-label={`${title} — Verlauf`}
                onpointermove={onPointerMove}
                onpointerleave={() => (hoverIndex = null)}
            >
                <!-- Raster: hauchdünn und zurückgenommen, es trägt keine Daten -->
                {#each ticks as tick}
                    <line
                        class="grid"
                        x1={PAD.left}
                        x2={PAD.left + plotWidth}
                        y1={y(tick)}
                        y2={y(tick)}
                    />
                    <text class="axis-label" x={PAD.left - 6} y={y(tick) + 3} text-anchor="end">
                        {formatTick(tick)}
                    </text>
                {/each}

                {#each xLabels as label}
                    <text
                        class="axis-label"
                        x={x(label.index)}
                        y={height - 6}
                        text-anchor="middle">{label.label}</text
                    >
                {/each}

                {#if series.length === 1}
                    <path class="area" d={areaPath(values[0])} fill="var(--series-1)" />
                {/if}

                {#each series as _s, i}
                    <path
                        class="line"
                        d={linePath(values[i])}
                        stroke={`var(--series-${i + 1})`}
                    />
                {/each}

                <!-- Endpunkt + Direktbeschriftung: der zuletzt gemessene Wert ist
                     der, nach dem am häufigsten gesucht wird. -->
                {#each endMarkers as marker}
                    <circle
                        class="end-dot"
                        cx={x(marker.index)}
                        cy={marker.y}
                        r="4.5"
                        fill={`var(--series-${marker.slot})`}
                    />
                    <text
                        class="end-label"
                        x={x(marker.index) + 9}
                        y={marker.labelY + 3.5}
                    >{formatValue(marker.value)}</text>
                {/each}

                {#if hoverIndex != null}
                    <line
                        class="crosshair"
                        x1={x(hoverIndex)}
                        x2={x(hoverIndex)}
                        y1={PAD.top}
                        y2={PAD.top + plotHeight}
                    />
                    {#each series as _s, i}
                        {@const value = values[i][hoverIndex]}
                        {#if value != null}
                            <circle
                                class="hover-dot"
                                cx={x(hoverIndex)}
                                cy={y(value)}
                                r="4"
                                fill={`var(--series-${i + 1})`}
                            />
                        {/if}
                    {/each}
                {/if}
            </svg>

            {#if hoverIndex != null}
                <div
                    class="tooltip"
                    class:flipped={tooltipFlipped}
                    style={`left: ${x(hoverIndex)}px; top: ${PAD.top}px`}
                >
                    <div class="tooltip-time">{formatFull(String(points[hoverIndex].t))}</div>
                    {#each series as s, i}
                        <div class="tooltip-row">
                            <span class="tooltip-key" style={`background: var(--series-${i + 1})`}></span>
                            <span class="tooltip-value">{formatValue(values[i][hoverIndex])}</span>
                            <span class="tooltip-label">{s.label}</span>
                        </div>
                    {/each}
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
    /* Reihenfarben: die ersten drei Slots der validierten Palette (blau, orange,
       aqua). Sie sind auf beiden Oberflächen farbfehlsichtigkeitssicher geprüft;
       die Dunkelvariante ist eigens gewählt, nicht bloß aufgehellt. */
    .chart-card {
        --series-1: #2a78d6;
        --series-2: #eb6834;
        --series-3: #1baf7a;
        --grid-ink: color-mix(in srgb, var(--text-muted) 40%, transparent);
        background: var(--surface-2);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: .6rem .7rem .4rem;
    }
    :global([data-theme='dark']) .chart-card {
        --series-1: #3987e5;
        --series-2: #d95926;
        --series-3: #199e70;
    }

    .chart-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: .5rem;
        margin-bottom: .3rem;
    }
    .chart-title { font-size: var(--text-sm); font-weight: 600; color: var(--text-1); }
    .table-toggle {
        background: none;
        border: 1px solid var(--border);
        border-radius: 4px;
        color: var(--text-2);
        font-size: var(--text-xs);
        padding: .1rem .4rem;
        cursor: pointer;
    }
    .table-toggle:hover { color: var(--color-primary); border-color: var(--color-primary); }

    .legend { display: flex; flex-wrap: wrap; gap: .75rem; margin-bottom: .2rem; }
    .legend-item {
        display: inline-flex;
        align-items: center;
        gap: .3rem;
        font-size: var(--text-xs);
        color: var(--text-2);
    }
    /* Linien-Key statt Farbklotz — die Marke im Diagramm ist ebenfalls eine Linie. */
    .legend-key { width: 14px; height: 2px; border-radius: 1px; }

    .plot { position: relative; }
    svg { display: block; overflow: visible; }

    .grid { stroke: var(--grid-ink); stroke-width: 1; }
    .axis-label { fill: var(--text-muted); font-size: 10px; }
    .line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
    .area { opacity: .1; stroke: none; }
    /* 2-px-Ring in Flächenfarbe, damit Endpunkte über der Linie lesbar bleiben. */
    .end-dot, .hover-dot { stroke: var(--surface-2); stroke-width: 2; }
    .end-label { fill: var(--text-2); font-size: 10px; font-weight: 600; }
    .crosshair { stroke: var(--text-muted); stroke-width: 1; }

    .tooltip {
        position: absolute;
        transform: translateX(8px);
        background: var(--surface-1);
        border: 1px solid var(--border);
        border-radius: 6px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, .18);
        padding: .35rem .5rem;
        pointer-events: none;
        min-width: 8rem;
        z-index: 2;
    }
    .tooltip.flipped { transform: translateX(calc(-100% - 8px)); }
    .tooltip-time { font-size: var(--text-xs); color: var(--text-muted); margin-bottom: .2rem; }
    .tooltip-row { display: flex; align-items: baseline; gap: .35rem; font-size: var(--text-xs); }
    .tooltip-key { width: 10px; height: 2px; border-radius: 1px; align-self: center; }
    .tooltip-value { font-weight: 700; color: var(--text-1); }
    .tooltip-label { color: var(--text-2); }

    .chart-empty { font-size: var(--text-sm); color: var(--text-muted); margin: .75rem 0; }

    .table-wrap { max-height: 16rem; overflow: auto; }
    .chart-table { width: 100%; border-collapse: collapse; font-size: var(--text-xs); }
    .chart-table th {
        position: sticky;
        top: 0;
        background: var(--surface-2);
        text-align: left;
        padding: .3rem .4rem;
        color: var(--text-muted);
        border-bottom: 1px solid var(--border);
    }
    .chart-table td { padding: .25rem .4rem; border-bottom: 1px solid var(--border); color: var(--text-2); }
</style>
