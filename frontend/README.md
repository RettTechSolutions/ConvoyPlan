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

| Route | Beschreibung |
|---|---|
| `/setup` | Ersteinrichtungs-Wizard (Superadmin + Erste Org + Domain + SSL) |
| `/login` | Globale Anmeldung |
| `/[org-code]/login` | Org-spezifische Anmeldung mit eigenem Branding |
| `/[org-code]/plan` | Planungsansicht mit interaktiver Karte |
| `/[org-code]/tracking` | Live-Tracking-Ansicht |
| `/[org-code]/share/[token]` | Öffentliche Routenansicht ohne Login |
| `/[org-code]/admin` | Org-Admin: Mitglieder, Leitstellen, Branding, System |
| `/admin` | Superadmin: Benutzer- und Org-Verwaltung |

> Alte Pfade `/plan` und `/admin` leiten automatisch auf die jeweilige org-spezifische URL um.

## Wichtige Stores

| Store | Datei | Beschreibung |
|---|---|---|
| `auth` | `src/lib/stores/auth.ts` | JWT-Token, Login-Status, Benutzerinfo |
| `org` | `src/lib/stores/org.ts` | Aktiver Org-Code-Slug, org-bewusster API-Client |
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
