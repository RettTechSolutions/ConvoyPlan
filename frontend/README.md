# MarschPlan – Frontend

SvelteKit-Frontend für MarschPlan. Svelte 5 mit Runes (`$state`, `$effect`, `$derived`), TypeScript, MapLibre GL für die Karte.

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

| Route | Beschreibung |
|---|---|
| `/setup` | Ersteinrichtungs-Wizard (Superadmin + Domain + SSL) |
| `/login` | Anmeldung |
| `/plan` | Planungsansicht mit interaktiver Karte |
| `/tracking` | Live-Tracking-Ansicht |
| `/share/[token]` | Öffentliche Routenansicht ohne Login |
| `/admin` | Superadmin-Benutzerverwaltung |

## Wichtige Stores

| Store | Datei | Beschreibung |
|---|---|---|
| `auth` | `src/lib/stores/auth.ts` | JWT-Token, Login-Status, Benutzerinfo |
| `convoy` | `src/lib/stores/convoy.ts` | Aktiver Marschverband und Wegpunkte |
| `map` | `src/lib/stores/map.ts` | MapLibre-Instanz und Layer-Zustand |
| `tracking` | `src/lib/stores/tracking.ts` | Live-Positionen per WebSocket |
| `lage` | `src/lib/stores/lage.ts` | GeoJSON-Lagedaten |

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
