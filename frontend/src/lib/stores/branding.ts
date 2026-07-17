import { writable } from 'svelte/store';

export interface Branding {
    app_name: string;
    logo_main_url: string | null;
    logo_horizontal_url: string | null;
    color_primary: string;
    color_primary_hover: string;
    color_accent: string;
    color_bg: string;
    color_surface: string;
    color_nav_bg: string;
    color_nav_text: string;
    color_text: string;
    color_text_muted: string;
}

export const BRANDING_DEFAULTS: Branding = {
    app_name: 'ConvoyPlan',
    logo_main_url: null,
    logo_horizontal_url: null,
    color_primary: '#E23D28',
    color_primary_hover: '#C23020',
    color_accent: '#3498db',
    color_bg: '#f5f3ee',
    color_surface: '#ffffff',
    color_nav_bg: '#2c3e50',
    color_nav_text: '#ecf0f1',
    color_text: '#2c3e50',
    color_text_muted: '#7f8c8d',
};

export function applyBranding(b: Branding): void {
    const root = document.documentElement;
    root.style.setProperty('--color-primary', b.color_primary);
    root.style.setProperty('--color-primary-hover', b.color_primary_hover);
    root.style.setProperty('--color-accent', b.color_accent);
    root.style.setProperty('--color-bg', b.color_bg);
    root.style.setProperty('--color-surface', b.color_surface);
    root.style.setProperty('--color-nav-bg', b.color_nav_bg);
    root.style.setProperty('--color-nav-text', b.color_nav_text);
    root.style.setProperty('--color-text', b.color_text);
    root.style.setProperty('--color-text-muted', b.color_text_muted);
}

/**
 * `brandingStore` hält immer das aktuell wirksame Branding (Komponenten wie
 * AppLogo lesen daraus). Außerhalb einer Org ist das das Plattform-Branding;
 * innerhalb von /o/[slug] das effektive Org-Branding. Das Plattform-Branding
 * wird separat gemerkt, damit es beim Verlassen der Org wiederhergestellt
 * werden kann.
 */
export const brandingStore = writable<Branding>(BRANDING_DEFAULTS);

let globalBranding: Branding = BRANDING_DEFAULTS;
let orgBrandingActive = false;

/** Root-Layout: Plattform-Branding setzen (überschreibt nie ein aktives Org-Branding). */
export function setGlobalBranding(b: Branding): void {
    globalBranding = b;
    if (orgBrandingActive) return;
    brandingStore.set(b);
    applyBranding(b);
}

/** Org-Layout: effektives Branding einer Organisation aktivieren. */
export function setOrgBranding(b: Branding): void {
    orgBrandingActive = true;
    brandingStore.set(b);
    applyBranding(b);
}

/** Org-Layout (beim Verlassen): zurück zum Plattform-Branding. */
export function clearOrgBranding(): void {
    if (!orgBrandingActive) return;
    orgBrandingActive = false;
    brandingStore.set(globalBranding);
    applyBranding(globalBranding);
}
