# Demo-Modus Banner — Design Spec

**Datum:** 2026-05-26  
**Status:** Approved

## Ziel

Alle eingeloggten Nutzer sollen sofort und dauerhaft sehen, wenn ConvoyPlan im Demo-Modus läuft (keine gültige Lizenz). Aktuell ist der Demo-Modus für normale Nutzer unsichtbar — nur Schreiboperationen schlagen still mit HTTP 402 fehl.

## Backend

### Neuer Endpunkt

```
GET /api/license/mode
```

- **Auth:** keine (public) — gibt keine sensiblen Daten zurück
- **Response:** `{ "demo_mode": true | false }`
- **Implementierung:** liest `validate_license(license_key, instance_id).valid` analog zu `license_guard.py`, gibt `demo_mode = not valid` zurück
- **Datei:** `backend/app/api/routes/license.py` — neuer Router-Endpunkt unterhalb der bestehenden

Der Endpunkt liegt unter `/api/license/` und ist damit bereits vom `LicenseGuardMiddleware` ausgenommen. Es werden keine Instance-ID, kein Key-Source, keine Kundendaten zurückgegeben.

## Frontend

### Daten-Fetch in `+layout.svelte`

- `onMount`: ruft `GET /api/license/mode` auf, **nur wenn** `$auth.token` gesetzt ist und die aktuelle Route keine Public Route ist (`/login`, `/share`, `/setup`)
- Speichert `demoMode: boolean` als lokale `$state`-Variable im Layout
- Kein Polling — einmaliger Fetch; Seite wird nach Lizenz-Aktivierung ohnehin neu geladen

### Banner-Darstellung

```
┌─────────────────────────────────────────────────────────────────────┐
│ ⚠  Demo-Modus — keine gültige Lizenz. Schreiboperationen gesperrt.  │
│                                          [Lizenz aktivieren →]       │
└─────────────────────────────────────────────────────────────────────┘
```

- **Position:** `position: sticky; top: 0; z-index: 1000` — erscheint über allem Seiteninhalt
- **Farbe:** Orange/Amber (`#f59e0b` Hintergrund, dunkler Text) — signalisiert Warnung, kein Fehler
- **Text:** „Demo-Modus — keine gültige Lizenz. Schreiboperationen sind gesperrt."
- **Link „Lizenz aktivieren →":** nur sichtbar wenn `$auth.is_superadmin === true`, verlinkt auf `/admin` (User scrollt dann zum Lizenz-Tab)
- **Normale User:** nur der Infotext, kein Link

### Datei-Änderungen

| Datei | Änderung |
|-------|----------|
| `backend/app/api/routes/license.py` | Neuer `GET /license/mode` Endpunkt |
| `frontend/src/routes/+layout.svelte` | Fetch + Banner-Rendering |

Keine neuen Dateien, kein separater Store (YAGNI — kann bei Bedarf ausgelagert werden).

## Nicht im Scope

- Polling / Live-Updates des Bannerstatus
- Banner auf Public Routes (Login, Share, Setup)
- Deaktivieren von Write-Buttons im UI (separates Feature)
