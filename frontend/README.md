# ConvoyPlan – Frontend

SvelteKit-Frontend für ConvoyPlan. Svelte 5 mit Runes (`$state`, `$effect`, `$derived`), TypeScript, MapLibre GL für die Karte.

## Voraussetzungen

- Node.js 20+
- npm

## Entwicklung

```bash
npm install
npm run dev
```

Der Dev-Server läuft auf `http://localhost:5173`. Das Backend muss erreichbar sein (Standard: `http://localhost:8000`).

Für lokale Entwicklung ohne Caddy `frontend/.env.local` anlegen:

```env
VITE_WS_HOST=localhost:8000
```

## Verfügbare npm-Skripte

| Befehl | Beschreibung |
|---|---|
| `npm run dev` | Dev-Server mit Hot Reload starten |
| `npm run build` | Produktions-Build erstellen |
| `npm run preview` | Produktions-Build lokal vorschaugen |
| `npm run check` | Svelte-Typecheck ausführen (`svelte-check`) |
| `npm run check:watch` | Typecheck im Watch-Modus |

## Routen

Org-spezifische Routen liegen unter dem Scope `/o/[slug]/`, wobei `[slug]` der
Org-Code der Organisation ist (4–8 Zeichen, beim Setup bzw. im Superadmin-Panel
vergeben).

| Route | Beschreibung |
|---|---|
| `/setup` | Ersteinrichtungs-Wizard (Superadmin + erste Org + Domain + SSL + Branding) |
| `/admin` | Superadmin-Portal — self-gated: zeigt bei fehlender Anmeldung direkt die Login-Maske (inkl. MFA und Passwort-vergessen) |
| `/o/[slug]/login` | Org-spezifische Anmeldung mit eigenem Branding |
| `/o/[slug]/plan` | Planungsansicht mit interaktiver Karte |
| `/o/[slug]/tracking` | Live-Tracking-Übersicht der Organisation |
| `/o/[slug]/tracking/[convoy_id]` | Live-Tracking eines einzelnen Konvois |
| `/o/[slug]/admin` | Org-Admin: Mitglieder, Leitstellen, Branding, System |
| `/track/[slug]` | Eigenständige Fahrer-Tracking-PWA („Convoy Tracking") — Position teilen per Tracking-ID/-Link |
| `/share/[token]` | Öffentliche Routenansicht ohne Login |

> Die separate globale `/login`-Route wurde entfernt; die Superadmin-Anmeldung
> ist in `/admin` integriert. Das alte `/plan` leitet auf die Startseite um.

## Wichtige Stores

| Store | Datei | Beschreibung |
|---|---|---|
| `auth` | `src/lib/stores/auth.ts` | JWT-Token, Login-Status, Benutzerinfo |
| `org` | `src/lib/stores/org.ts` | Aktiver Org-Code-Slug, org-bewusster API-Client |
| `convoy` | `src/lib/stores/convoy.ts` | Aktiver Marschverband und Wegpunkte |
| `map` | `src/lib/stores/map.ts` | MapLibre-Instanz und Layer-Zustand |
| `tracking` | `src/lib/stores/tracking.ts` | Live-Positionen per WebSocket |
| `branding` | `src/lib/stores/branding.ts` | App-Name, Farben und Logo der aktiven Org |

## Produktions-Build

```bash
npm run build
```

Der Build liegt anschließend unter `build/`. Im Docker-Setup wird das Image mit dem Node-Adapter gebaut und direkt als Container gestartet.

## Typen prüfen

```bash
npm run check
```

Läuft auch automatisch in der CI-Pipeline bei jedem Push und Pull Request.
