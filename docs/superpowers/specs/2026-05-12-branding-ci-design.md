# Branding & CI-Anpassung

## Überblick

Systemweite Branding-Konfiguration: Organisationen können Logo, App-Name und Farbschema anpassen. Die Konfiguration erfolgt im Setup-Wizard (einmalig) und im Superadmin-Menü (nachträglich). Der Softwarename "ConvoyPlan" bleibt als hardcodierter "Powered by"-Hinweis in der UI erhalten.

---

## Datenmodell

Kein neues DB-Schema. Die bestehende `system_settings`-Tabelle (Key/Value) wird um folgende Keys erweitert:

| Key | Typ | Default |
|-----|-----|---------|
| `branding.app_name` | String | `ConvoyPlan` |
| `branding.logo_main` | String (Pfad) | `` (leer = Original) |
| `branding.logo_horizontal` | String (Pfad) | `` (leer = Original) |
| `branding.color_primary` | Hex-String | `#E23D28` |
| `branding.color_primary_hover` | Hex-String | `#C23020` |
| `branding.color_accent` | Hex-String | `#3498db` |
| `branding.color_bg` | Hex-String | `#f5f3ee` |
| `branding.color_surface` | Hex-String | `#ffffff` |
| `branding.color_nav_bg` | Hex-String | `#2c3e50` |
| `branding.color_nav_text` | Hex-String | `#ecf0f1` |
| `branding.color_text` | Hex-String | `#2c3e50` |
| `branding.color_text_muted` | Hex-String | `#7f8c8d` |

Default-Werte werden beim ersten Start eingetragen falls noch nicht vorhanden (Alembic-Migration oder Startup-Hook).

Logos werden im persistenten Volume unter `/uploads/logos/` gespeichert.

---

## Backend

### Neuer Router `backend/app/api/routes/branding.py`

| Method | Endpoint | Auth | Funktion |
|--------|----------|------|---------|
| GET | `/api/branding` | öffentlich | Alle Branding-Werte als JSON |
| PUT | `/api/branding` | superadmin | Farbwerte + App-Name speichern |
| POST | `/api/branding/logo/main` | superadmin | Hauptlogo hochladen |
| POST | `/api/branding/logo/horizontal` | superadmin | Horizontales Logo hochladen |

`GET /api/branding` ist ohne Login abrufbar (benötigt vor Login-Seite).

**Response-Schema `BrandingResponse`:**
```python
class BrandingResponse(BaseModel):
    app_name: str
    logo_main_url: str | None      # None = Original verwenden
    logo_horizontal_url: str | None
    color_primary: str
    color_primary_hover: str
    color_accent: str
    color_bg: str
    color_surface: str
    color_nav_bg: str
    color_nav_text: str
    color_text: str
    color_text_muted: str
```

**Logo-Upload:**
- Erlaubte Formate: PNG, JPG, SVG
- Max. Dateigröße: 2 MB
- Speicherort: `/uploads/logos/{main|horizontal}.{ext}`
- Statische Dateien werden über FastAPI's `StaticFiles` unter `/uploads/` ausgeliefert

**Router-Registrierung:** `app.include_router(branding.router, prefix="/api")`

**Statische Dateien:** `app.mount("/uploads", StaticFiles(directory="/uploads"), name="uploads")`

---

## Setup-Wizard

Neuer **Schritt 3 "Branding"** zwischen Server-Konfiguration und Abschluss:

- **App-Name** — Textfeld (Placeholder: "z.B. Feuerwehr München")
- **Hauptlogo** — Datei-Upload mit Bildvorschau (PNG/JPG/SVG, max 2 MB)
- **Horizontales Logo** — Datei-Upload mit Bildvorschau
- **Primärfarbe** — `<input type="color">` Color-Picker; `color_primary_hover` wird automatisch 10% dunkler abgeleitet (clientseitig)
- **Erweiterte Farben** — aufklappbarer Bereich mit den 8 restlichen Farbvariablen, je mit Color-Picker und Label
- **"Powered by ConvoyPlan"** — statischer, nicht entfernbarer Hinweis am unteren Rand des Schritts

Der Schritt ist **überspringbar** — ein "Überspringen"-Button behält die Defaults. Branding-Daten werden erst beim Abschluss des Wizards gespeichert (erst Text/Farben via `PUT /api/branding`, dann Logos via `POST /api/branding/logo/*` falls hochgeladen).

---

## Superadmin-Menü

Neuer Tab **"Branding"** in `/admin` (neben "Benutzer" und "Leitstellen"):

- Identisches Formular wie im Setup-Wizard
- **Live-Vorschau**: Farbänderungen werden sofort via CSS Custom Properties auf `:root` angewendet, bevor gespeichert wird
- **"Defaults wiederherstellen"**-Button setzt alle Werte auf ConvoyPlan-Defaults zurück
- Speichern via `PUT /api/branding` — wirkt sofort für alle User ohne Reload
- Logo-Upload: Datei auswählen → Vorschau erscheint → automatisch hochgeladen und gespeichert

---

## Frontend

### Branding-Store `frontend/src/lib/stores/branding.ts`

```typescript
interface Branding {
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
```

Svelte-Store mit `writable<Branding>`. Funktion `applyBranding(b: Branding)` setzt alle CSS Custom Properties auf `document.documentElement`.

### Root-Layout `+layout.svelte`

Beim App-Start: `GET /api/branding` aufrufen, `applyBranding()` ausführen, Store befüllen. Geschieht vor dem ersten Render (in `<script>` mit `onMount` oder in `+layout.ts` load function).

### CSS-Migration

Alle hardcodierten Hex-Farben in `.svelte`-Dateien werden durch CSS Custom Properties ersetzt:
- `#E23D28` → `var(--color-primary)`
- `#C23020` → `var(--color-primary-hover)`
- `#3498db` → `var(--color-accent)`
- `#f5f3ee` → `var(--color-bg)`
- `#ffffff` → `var(--color-surface)`
- `#2c3e50` → `var(--color-nav-bg)`
- `#ecf0f1` → `var(--color-nav-text)`
- `#2c3e50` → `var(--color-text)` (Kontext-abhängig)
- `#7f8c8d` → `var(--color-text-muted)`

### AppLogo.svelte

Liest `logo_main_url` und `logo_horizontal_url` aus dem Branding-Store. Fallback auf `/Hauptlogo.svg` bzw. `/LogoHorizontal.svg` wenn leer.

### "Powered by"-Footer

Jede Seite (via `+layout.svelte`) erhält einen kleinen Footer:

```
Powered by ConvoyPlan
```

Klein, dezent (Schriftgröße .72rem, `color-text-muted`), am unteren Rand des Layouts.

### Browser-Tab und Navbar

`<title>` und Navbar-Titel zeigen `$brandingStore.app_name` statt "ConvoyPlan".

---

## Berechtigungen

| Aktion | Berechtigung |
|--------|-------------|
| Branding lesen | Öffentlich (kein Login) |
| Branding schreiben | `is_superadmin = True` |
| Logos hochladen | `is_superadmin = True` |

---

## Nicht im Scope

- Mehrere Themes/Mandanten parallel
- Dark-Mode-Umschaltung
- Schriftarten-Auswahl
- Animationen oder weitere visuelle Effekte
