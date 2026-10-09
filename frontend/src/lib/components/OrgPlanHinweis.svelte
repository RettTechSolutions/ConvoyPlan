<script lang="ts">
    /**
     * Hinweis auf den Plan der eigenen Organisation (Hosting, Einsatz-Paket).
     *
     * Ohne Plan zeigt er nichts — der Normalfall jeder eigenen Installation.
     * Grenzen sind weich (backend/app/services/org_plan.py): eine
     * Überschreitung wird hier gemeldet, aber nichts wird abgewiesen. Erst nach
     * Ablauf samt Kulanz ist die Organisation nur noch lesbar, und das soll
     * jeder sehen, nicht nur der Admin — sonst sucht ein Planer den Fehler
     * beim Speichern an der falschen Stelle.
     */
    import { onMount } from 'svelte';
    import { orgPlanApi, type OrgPlanState } from '$lib/api';

    let { role }: { role: 'beobachter' | 'fahrer' | 'planer' | 'admin' } = $props();

    let plan = $state<OrgPlanState | null>(null);

    onMount(async () => {
        try {
            plan = await orgPlanApi.get();
        } catch {
            // Ein fehlender Hinweis ist besser als eine Fehlermeldung, die
            // mit der Arbeit des Benutzers nichts zu tun hat.
        }
    });

    const plant = $derived(role === 'admin' || role === 'planer');

    function datum(iso: string | null): string {
        if (!iso) return '';
        const [j, m, t] = iso.split('-');
        return `${t}.${m}.${j}`;
    }

    const text = $derived.by(() => {
        if (!plan?.plan) return null;
        if (plan.locked) {
            return {
                stufe: 'sperre',
                text: `Das Paket „${plan.label}“ ist am ${datum(plan.valid_until)} abgelaufen. Die Organisation ist nur noch lesbar; alle Daten bleiben erhalten.`,
            };
        }
        if (plan.expired) {
            return {
                stufe: 'warnung',
                text: `Das Paket „${plan.label}“ ist am ${datum(plan.valid_until)} abgelaufen. Ab dem ${datum(plan.locked_from)} ist die Organisation nur noch lesbar.`,
            };
        }
        if (plan.days_left !== null && plan.days_left <= 7) {
            return {
                stufe: 'info',
                text: `Das Paket „${plan.label}“ läuft am ${datum(plan.valid_until)} ab.`,
            };
        }
        if (!plant) return null;
        const ueber: string[] = [];
        if (plan.vehicles_over) ueber.push(`${plan.vehicles} Fahrzeuge (enthalten: ${plan.max_vehicles})`);
        if (plan.planners_over) ueber.push(`${plan.planners} Planerzugänge (enthalten: ${plan.max_planners})`);
        if (plan.trackers_over) ueber.push(`${plan.trackers} Tracker (enthalten: ${plan.max_trackers})`);
        if (ueber.length === 0) return null;
        return {
            stufe: 'info',
            text: `Mehr genutzt als im Paket „${plan.label}“ enthalten: ${ueber.join(', ')}. Es ist nichts eingeschränkt — bitte das Paket anpassen lassen.`,
        };
    });
</script>

{#if text}
    <div class="plan-hinweis {text.stufe}" role={text.stufe === 'info' ? 'status' : 'alert'}>
        <span>{text.text}</span>
        <a href="mailto:anfrage@convoyplan.de?subject=ConvoyPlan%20Paket">anfrage@convoyplan.de</a>
    </div>
{/if}

<style>
    .plan-hinweis {
        position: sticky;
        top: 0;
        z-index: 999;
        padding: 0.5rem 1.25rem;
        display: flex;
        justify-content: center;
        align-items: center;
        flex-wrap: wrap;
        gap: 0.25rem 1.25rem;
        font-size: 0.875rem;
        font-weight: 500;
        text-align: center;
        color: #1c1917;
    }
    .plan-hinweis.sperre { background: #f87171; }
    .plan-hinweis.warnung { background: #f59e0b; }
    .plan-hinweis.info { background: #fde68a; }
    .plan-hinweis a {
        color: inherit;
        text-decoration: underline;
        font-weight: 700;
        white-space: nowrap;
    }
</style>
