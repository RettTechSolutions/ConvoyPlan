# Multi-Tenancy: Org-Isolation Design

**Datum:** 2026-05-27  
**Status:** Approved  
**Scope:** Backend + Frontend — vollständige Org-Isolation nach HiOrg-Vorbild

---

## Ziel

Organisations-Kontext wird vor dem Login festgelegt. Jede Org hat eine eigene URL.
Orgs sehen sich gegenseitig nicht — weder Daten noch User. Ein User kann weiterhin in
mehreren Orgs Mitglied sein, loggt sich aber pro Org separat ein und erhält pro Session
einen org-gebundenen JWT.

---

## 1. Datenmodell

### `organizations` — neues Feld

```sql
slug  VARCHAR(80)  NOT NULL  UNIQUE
```

- URL-sicherer Bezeichner, z.B. `rettdienst-muenchen`
- Wird beim Erstellen der Org vergeben (Admin oder Setup-Wizard)
- **Unveränderlich** nach Erstellung (Umbenennen würde alle gespeicherten Links brechen)
- Erlaubte Zeichen: `[a-z0-9-]`, Länge 2–80

Keine weiteren Schemaänderungen. `user_organizations` bleibt n:m.

### JWT-Payload (erweitert)

```jsonc
{
  "sub":           "<user_uuid>",
  "org_id":        "<org_uuid>",    // null bei Superadmin
  "org_slug":      "rettdienst",    // null bei Superadmin
  "role":          "planer",        // aus user_organizations; null bei Superadmin
  "is_superadmin": false,
  "exp":           1234567890
}
```

Multi-Org-User erhalten **pro Org-Login einen eigenen Token**. Kein Org-Switcher,
kein Session-Sharing.

---

## 2. Login-Flow

### Schritt 1 — Org-Einstieg `/`

- Einziges Eingabefeld: Organisations-Code (= slug)
- `GET /api/auth/org-lookup?slug={code}` — öffentlich, liefert `{ name }` oder 404
- Timing-normalisiert (dummy-sleep) um Org-Enumeration zu verhindern
- Erfolg → Redirect `/o/{slug}/login`

### Schritt 2 — Org-Login `/o/{slug}/login`

- Seite zeigt Org-Namen (`"Anmelden bei Rettdienst München"`)
- Formular: E-Mail + Passwort (kein sichtbares Org-Feld)
- `POST /api/auth/login` mit Body `{ email, password, org_slug }`

**Backend-Logik:**
```
1. Org per slug → 404 falls unbekannt
2. User per email + Passwort → 401 (kein Hinweis ob Org oder User falsch)
3. UserOrganization(user, org) → 401 falls kein Mitglied
4. JWT mit org_id + org_slug + role ausstellen
5. Token-Key im Frontend: token__{slug}
```

### Superadmin-Login `/login`

- Bestehende Route, kein Slug
- `org_slug` im Body weggelassen → Backend erkennt Superadmin-Pfad
- JWT hat `org_id: null`, `role: null`, `is_superadmin: true`
- Zugang nur zu `/admin/` (globale Verwaltung), nicht zu Org-Routes

### Org-Wechsel

Kein spezieller UI-Flow. User öffnet `/o/andere-org/login` in neuem Tab →
neuer Token für diese Org. Token-Keys sind slug-spezifisch, Sessions kollidieren nicht.

---

## 3. Frontend-Routing

### URL-Struktur

```
/                               → Org-Code-Eingabe
/login                          → Superadmin-Login (bleibt)
/setup                          → Setup-Wizard (bleibt)
/tracking/[token]               → öffentlich, kein Org-Kontext (bleibt)
/share/[token]                  → öffentlich (bleibt)

/o/[slug]/                      → Org-Root (redirect → ./plan)
/o/[slug]/login                 → Org-Login
/o/[slug]/plan                  → Konvoi-Liste  (war /plan)
/o/[slug]/plan/[convoyId]       → Planung        (war /plan/[convoyId])
/o/[slug]/admin                 → Org-Admin      (war /admin, nur Org-Daten)
/o/[slug]/tracking/[convoyId]   → Auth-Tracking   (Org-Members, war /tracking mit Login)
```

### `o/[slug]/+layout.svelte` — Org-Guard

```
1. Slug aus URL-Param lesen
2. JWT aus localStorage[token__{slug}] laden
3. JWT fehlt oder abgelaufen → redirect /o/{slug}/login
4. JWT.org_slug !== URL-Slug → redirect /o/{slug}/login
5. Org-Metadaten laden (Name, Branding)
6. orgStore befüllen
7. Kind-Routen rendern
```

### `$orgStore` — globaler Context

```typescript
interface OrgContext {
  slug:      string
  org_id:    string
  org_name:  string
  user_id:   string
  user_role: 'beobachter' | 'fahrer' | 'planer' | 'admin'
}
```

### API-Client

Bestehender `api`-Client liest Token aus `localStorage[token__{slug}]`.
Der aktive Slug wird aus `$orgStore` gelesen. Kein globaler Token mehr —
immer org-spezifisch.

---

## 4. Backend-Isolation

### Dependency-Hierarchie

```python
get_token_data(credentials)       # neu — dekodiert JWT, gibt TokenData zurück
  ├── get_current_user(token_data, db)   # nutzt token_data.user_id
  └── get_org_context(token_data, db)   # nutzt token_data.org_id
        └── require_role(min_role)
```

**`TokenData`** — neues Schema in `app/api/deps.py`:
```python
class TokenData(BaseModel):
    user_id:      UUID
    org_id:       UUID | None   # None bei Superadmin
    org_slug:     str  | None
    role:         str  | None
    is_superadmin: bool
```

`get_current_user` und `get_org_context` erhalten `token_data: TokenData = Depends(get_token_data)`
statt das JWT selbst zu dekodieren. Kein Feld auf dem User-ORM-Modell nötig.

**`get_org_context`:**
```python
async def get_org_context(
    token_data: TokenData = Depends(get_token_data),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, Organization, str]:
    if not token_data.org_id:        # Superadmin-Token hat kein org_id
        raise HTTPException(403, "Org context required")
    user = await db.get(User, token_data.user_id)
    org  = await db.get(Organization, token_data.org_id)
    if not org:
        raise HTTPException(404, "Organisation nicht gefunden")
    mem = await db.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == user.id,
            UserOrganization.organization_id == org.id,
        )
    )
    membership = mem.scalar_one_or_none()
    if not membership:
        raise HTTPException(403, "Kein Mitglied dieser Organisation")
    return user, org, membership.role
```

### Query-Isolation

`org_id` kommt **ausschließlich aus dem JWT** — nie als URL-Parameter.
Manipulation der URL kann nicht auf fremde Org-Daten zugreifen.

```python
# Beispiel: Convoy-Liste
async def list_convoys(
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    result = await db.execute(
        select(Convoy).where(Convoy.organization_id == org.id)
    )
    return result.scalars().all()
```

Gleiches Muster für: Vehicles, Waypoints, Lage-Layer, Leitstellen, Tracking.

### Neue Endpoints

| Endpoint | Auth | Beschreibung |
|---|---|---|
| `GET /api/auth/org-lookup?slug=` | öffentlich | Org-Name für Login-Seite |
| `POST /api/auth/login` | — | erweitert um `org_slug` |

### Superadmin-Endpoints

Bleiben unter `/api/admin/` mit `require_superadmin`-Dependency.
Superadmin sieht alle Orgs, alle User, alle Ressourcen — kein Org-Filter.

---

## 5. Migration

### Alembic-Migration

```sql
-- 1. Spalte nullable hinzufügen
ALTER TABLE organizations ADD COLUMN slug VARCHAR(80);

-- 2. Slugs aus Namen generieren
--    "Rettdienst München" → "rettdienst-munchen"
UPDATE organizations
SET slug = lower(
    regexp_replace(
        translate(name, 'äöüÄÖÜß', 'aouaous'),
        '[^a-z0-9]+', '-', 'g'
    )
);

-- 3. Duplikate mit Suffix versehen (-2, -3, ...)
--    (in Python-Migration-Schritt umgesetzt)

-- 4. Constraint setzen
ALTER TABLE organizations ALTER COLUMN slug SET NOT NULL;
CREATE UNIQUE INDEX idx_organizations_slug ON organizations(slug);
```

### Setup-Wizard

Schritt 1 (Superadmin-Erstellung) bekommt zwei neue Felder:
- **Organisations-Name** (z.B. `Rettdienst München`)
- **Organisations-Slug** (auto-generiert, editierbar, validiert auf `[a-z0-9-]`)

Die erste Org wird beim Setup angelegt und der Superadmin wird automatisch
als `admin` eingetragen.

### Bestehende Tokens

JWT-Tokens ohne `org_id` werden nach dem Deploy funktionslos (Org-Guard
schlägt fehl). Alle Users müssen sich neu einloggen. Kein expliziter
Forced-Logout nötig — JWT-Expiry oder optionale `JWT_SECRET`-Rotation.

### Ressourcen ohne Org-Zuordnung

Convoys und Vehicles ohne `organization_id` bleiben in der DB erhalten.
Sie sind im Superadmin-Panel sichtbar, tauchen in keinem Org-Scope auf.
Superadmin kann sie manuell einer Org zuweisen.

---

## Nicht im Scope

- Org-Selbstregistrierung (Orgs werden weiterhin vom Superadmin angelegt)
- Slug-Umbenennung nach Erstellung
- Org-übergreifende Konvoi-Zusammenarbeit
- Subdomain-basiertes Routing
