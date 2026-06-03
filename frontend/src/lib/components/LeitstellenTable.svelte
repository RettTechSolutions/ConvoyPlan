<script lang="ts" module>
    // AGS-Präfix (erste zwei Ziffern des Kreisschlüssels) → Bundesland.
    const STATE_NAMES: Record<string, string> = {
        '01': 'Schleswig-Holstein', '02': 'Hamburg', '03': 'Niedersachsen', '04': 'Bremen',
        '05': 'Nordrhein-Westfalen', '06': 'Hessen', '07': 'Rheinland-Pfalz', '08': 'Baden-Württemberg',
        '09': 'Bayern', '10': 'Saarland', '11': 'Berlin', '12': 'Brandenburg',
        '13': 'Mecklenburg-Vorpommern', '14': 'Sachsen', '15': 'Sachsen-Anhalt', '16': 'Thüringen',
    };
    const NO_STATE = 'Ohne Landkreis-Zuordnung';

    export function bundeslandOf(ls: { district_codes?: string[] }): string {
        const c = ls.district_codes?.[0];
        if (!c) return NO_STATE;
        return STATE_NAMES[c.slice(0, 2)] ?? 'Unbekannt';
    }

    const STATUS_LABEL: Record<string, string> = {
        global: 'Global', local: 'Lokal', pending: 'Vorschlag', rejected: 'Abgelehnt',
    };
</script>

<script lang="ts">
    import type { Snippet } from 'svelte';
    import type { Leitstelle } from '$lib/api';

    interface Props {
        items: Leitstelle[];
        showOrg?: boolean;
        actions?: Snippet<[Leitstelle]>;
        /** Statuslabel-Override (z.B. Org-Portal: pending = „Eingereicht"). */
        statusLabels?: Record<string, string>;
    }
    let { items, showOrg = false, actions, statusLabels }: Props = $props();

    type SortKey = 'name' | 'anrufgruppe' | 'status' | 'org' | 'kanaele' | 'grenzen';
    let search = $state('');
    let sortKey = $state<SortKey>('name');
    let sortDir = $state<'asc' | 'desc'>('asc');
    let groupByState = $state(true);
    let collapsed = $state<Set<string>>(new Set());

    const labelFor = (s: string) => statusLabels?.[s] ?? STATUS_LABEL[s] ?? s;
    const orgName = (ls: Leitstelle) => ls.org_name ?? ls.proposed_by_org_name ?? '';

    function toggleSort(k: SortKey) {
        if (sortKey === k) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
        else { sortKey = k; sortDir = 'asc'; }
    }
    const sortIcon = (k: SortKey) => (sortKey === k ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '');

    let filtered = $derived.by(() => {
        const q = search.trim().toLowerCase();
        if (!q) return items;
        return items.filter((ls) =>
            [ls.name, ls.anrufgruppe, orgName(ls), labelFor(ls.status), bundeslandOf(ls)]
                .join(' ').toLowerCase().includes(q)
        );
    });

    function cmp(a: Leitstelle, b: Leitstelle): number {
        let av: string | number, bv: string | number;
        switch (sortKey) {
            case 'anrufgruppe': av = a.anrufgruppe; bv = b.anrufgruppe; break;
            case 'status': av = labelFor(a.status); bv = labelFor(b.status); break;
            case 'org': av = orgName(a); bv = orgName(b); break;
            case 'kanaele': av = a.zusatz_kanaele.length; bv = b.zusatz_kanaele.length; break;
            case 'grenzen': av = a.has_geometry ? 1 : 0; bv = b.has_geometry ? 1 : 0; break;
            default: av = a.name; bv = b.name;
        }
        const an = Number(av), bn = Number(bv);
        const numeric = typeof av === 'number' || (av !== '' && bv !== '' && !isNaN(an) && !isNaN(bn));
        const r = numeric ? an - bn : String(av).localeCompare(String(bv), 'de');
        return sortDir === 'asc' ? r : -r;
    }

    let sorted = $derived([...filtered].sort(cmp));

    let groups = $derived.by(() => {
        const m = new Map<string, Leitstelle[]>();
        for (const ls of sorted) {
            const g = bundeslandOf(ls);
            let arr = m.get(g);
            if (!arr) { arr = []; m.set(g, arr); }
            arr.push(ls);
        }
        return [...m.entries()].sort((a, b) => {
            if (a[0] === NO_STATE) return 1;
            if (b[0] === NO_STATE) return -1;
            return a[0].localeCompare(b[0], 'de');
        });
    });

    function toggleGroup(name: string) {
        const next = new Set(collapsed);
        if (next.has(name)) next.delete(name); else next.add(name);
        collapsed = next;
    }

    let colCount = $derived(3 + (showOrg ? 1 : 0) + 2 + (actions ? 1 : 0));
</script>

<div class="lst-toolbar">
    <label class="lst-toggle">
        <input type="checkbox" bind:checked={groupByState} /> Nach Bundesland gruppieren
    </label>
    <input class="lst-search" type="search" placeholder="🔍 Suchen…" bind:value={search} />
</div>

<table class="lst-table">
    <thead>
        <tr>
            <th><button type="button" class="th-sort" onclick={() => toggleSort('name')}>Name{sortIcon('name')}</button></th>
            <th><button type="button" class="th-sort" onclick={() => toggleSort('anrufgruppe')}>Anrufgruppe{sortIcon('anrufgruppe')}</button></th>
            <th><button type="button" class="th-sort" onclick={() => toggleSort('status')}>Status{sortIcon('status')}</button></th>
            {#if showOrg}
                <th><button type="button" class="th-sort" onclick={() => toggleSort('org')}>Organisation{sortIcon('org')}</button></th>
            {/if}
            <th><button type="button" class="th-sort" onclick={() => toggleSort('kanaele')}>Zusatzkanäle{sortIcon('kanaele')}</button></th>
            <th><button type="button" class="th-sort" onclick={() => toggleSort('grenzen')}>Grenzen{sortIcon('grenzen')}</button></th>
            {#if actions}<th></th>{/if}
        </tr>
    </thead>
    <tbody>
        {#if sorted.length === 0}
            <tr><td colspan={colCount} class="hint" style="text-align:center">{items.length === 0 ? 'Noch keine Leitstellen erfasst.' : 'Keine Treffer.'}</td></tr>
        {:else if groupByState}
            {#each groups as [name, rows] (name)}
                <tr class="group-row" onclick={() => toggleGroup(name)}>
                    <td colspan={colCount}>
                        <span class="group-caret">{collapsed.has(name) ? '▸' : '▾'}</span>
                        {name} <span class="group-count">({rows.length})</span>
                    </td>
                </tr>
                {#if !collapsed.has(name)}
                    {#each rows as ls (ls.id)}{@render row(ls)}{/each}
                {/if}
            {/each}
        {:else}
            {#each sorted as ls (ls.id)}{@render row(ls)}{/each}
        {/if}
    </tbody>
</table>

{#snippet row(ls: Leitstelle)}
    <tr>
        <td>{ls.name}</td>
        <td><code>{ls.anrufgruppe}</code></td>
        <td>
            <span class="ls-badge ls-{ls.status}">{labelFor(ls.status)}</span>
            {#if ls.status === 'rejected' && ls.review_note}
                <div class="reject-note" title={ls.review_note}>Grund: {ls.review_note}</div>
            {/if}
        </td>
        {#if showOrg}<td>{orgName(ls) || '–'}</td>{/if}
        <td>{ls.zusatz_kanaele.length > 0 ? ls.zusatz_kanaele.length : '–'}</td>
        <td>{ls.has_geometry ? '✓' : '✗'}</td>
        {#if actions}<td class="actions-cell">{@render actions(ls)}</td>{/if}
    </tr>
{/snippet}

<style>
    .lst-toolbar { display: flex; align-items: center; justify-content: space-between; gap: .75rem; margin-bottom: .6rem; flex-wrap: wrap; }
    .lst-toggle { display: flex; align-items: center; gap: .35rem; font-size: var(--text-xs); color: var(--text-2); cursor: pointer; }
    .lst-search { flex: 0 1 240px; margin-left: auto; padding: .35rem .6rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
    .lst-search::placeholder { color: var(--text-muted); }

    .lst-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
    .lst-table th { text-align: left; padding: 0; border-bottom: 1px solid var(--border); }
    .lst-table td { padding: .5rem; border-bottom: 1px solid var(--border); vertical-align: middle; color: var(--text-2); }
    .th-sort { width: 100%; text-align: left; padding: .5rem; background: none; border: none; cursor: pointer; color: var(--text-muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .04em; white-space: nowrap; }
    .th-sort:hover { color: var(--text-1); }

    .group-row { cursor: pointer; }
    .group-row td { background: var(--surface-2); font-weight: 600; color: var(--text-1); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .03em; }
    .group-row:hover td { background: var(--surface-1); }
    .group-caret { display: inline-block; width: 1em; color: var(--text-muted); }
    .group-count { color: var(--text-muted); font-weight: 400; }

    .actions-cell { white-space: nowrap; }
    .actions-cell > :global(div) { display: flex; gap: .3rem; }
    .hint { color: var(--text-muted); font-size: var(--text-sm); }
    code { background: var(--surface-2); padding: .1rem .3rem; border-radius: 3px; font-size: var(--text-xs); font-family: monospace; color: var(--text-1); }

    .ls-badge { display: inline-block; padding: .05rem .4rem; border-radius: 10px; font-size: var(--text-xs); font-weight: 600; }
    .ls-badge.ls-global { background: #1e3a8a; color: #bfdbfe; }
    .ls-badge.ls-local { background: #334155; color: #cbd5e1; }
    .ls-badge.ls-pending { background: #78350f; color: #fde68a; }
    .ls-badge.ls-rejected { background: #7f1d1d; color: #fecaca; }
    .reject-note { font-size: var(--text-xs); color: var(--text-muted); margin-top: .15rem; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
