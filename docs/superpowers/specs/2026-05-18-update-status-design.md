# Update-Status im Admin-Bereich — Design Spec

**Datum:** 2026-05-18
**Scope:** Updater schreibt Deploy-Status in ein Shared Volume; Backend stellt zwei Endpoints bereit; Admin-Frontend zeigt Update-Verfügbarkeit und ermöglicht manuellen Trigger.

---

## Ziel

Superadmins sollen im Admin-Bereich sehen können ob eine neue Version auf GitHub verfügbar ist, und das Update manuell anstoßen können, ohne SSH-Zugang zum Server.

---

## Architektur

### Shared Volume `update_status`

Ein neues Docker-Named-Volume wird in `docker-compose.yml` deklariert und in zwei Services gemountet:

| Service   | Mountpfad        |
|-----------|-----------------|
| `updater` | `/update_status` |
| `backend` | `/update_status` |

Das Volume enthält maximal zwei Dateien:

- **`status.json`** — Schreibt der Updater nach jedem erfolgreichen Deploy:
  ```json
  {"deployed_sha": "2cc66e7", "deployed_at": "2026-05-18T12:50:29Z"}
  ```
- **`trigger`** — Legt der Backend-Endpoint an, um einen sofortigen Deploy auszulösen. Updater löscht sie nach Verarbeitung.

### Updater-Änderungen (`docker/updater/update.sh`)

1. Nach jedem erfolgreichen Deploy: `status.json` in `/update_status/` schreiben.
2. Trigger-Polling: In der Hauptschleife, vor dem `sleep`, prüfen ob `/update_status/trigger` existiert. Falls ja:
   - Datei sofort löschen (verhindert Doppel-Trigger).
   - Normalen Update-Ablauf (fetch → reset → compose up) ausführen, unabhängig davon ob SHA sich geändert hat.

### Backend — neue Settings

`backend/app/config.py` erhält zwei optionale Felder:
- `github_token: str = ""` — für GitHub API (höheres Rate-Limit; 60/h ohne Token, 5000/h mit).
- `github_repo: str = "RettTechSolutions/MarschPlan"` — Owner/Repo für die API-Abfrage.

### Backend — neue Endpoints (`backend/app/api/routes/admin.py`)

Beide Endpoints sind mit `require_superadmin` gesichert.

#### `GET /api/admin/update-status`

Ablauf:
1. Liest `/update_status/status.json` — wenn nicht vorhanden, `deployed_sha = null`.
2. Fragt GitHub REST API ab: `GET https://api.github.com/repos/{repo}/commits/main` mit optionalem `Authorization: Bearer {token}` Header. Timeout 5s.
3. Gibt zurück:

```json
{
  "deployed_sha": "2cc66e7",
  "deployed_at": "2026-05-18T12:50:29Z",
  "remote_sha": "a1d7829",
  "update_available": true,
  "github_reachable": true
}
```

Bei GitHub-Fehler: `github_reachable: false`, `remote_sha: null`, `update_available: false`.

#### `POST /api/admin/trigger-update`

Ablauf:
1. Prüft ob `/update_status/trigger` bereits existiert (Doppel-Trigger verhindern).
2. Erstellt die Datei `/update_status/trigger`.
3. Gibt HTTP 202 zurück.

Bei bereits existierendem Trigger: HTTP 409 mit Meldung "Update already triggered".

### Frontend — neuer Tab "System" (`frontend/src/routes/admin/+page.svelte`)

Neuer vierter Tab wird zur `activeTab`-Union hinzugefügt: `'benutzer' | 'leitstellen' | 'branding' | 'system'`.

#### Update-Status-Card

Zeigt:
- **Deployed:** kurzer SHA (7 Zeichen) + Zeitstempel
- **Aktuell auf GitHub:** kurzer Remote-SHA
- **Badge:** `Aktuell ✓` (grün) oder `Update verfügbar ↑` (orange)
- **Button "Jetzt updaten":** disabled wenn `update_available === false`, wenn Trigger läuft, oder wenn GitHub nicht erreichbar.

#### Trigger-Flow

1. Button-Klick → `POST /api/admin/trigger-update` → Spinner anzeigen.
2. Polling alle 3s auf `GET /api/admin/update-status`.
3. Erfolg: wenn `deployed_sha` sich geändert hat und `update_available === false`.
4. Timeout: nach 3 Minuten (60 Polls) → Fehlermeldung "Timeout — bitte Logs prüfen".
5. Bei HTTP-Fehler vom Trigger-Endpoint: Fehlermeldung direkt anzeigen.

---

## Dateiänderungen

**Erstellen:**
- keine neuen Dateien

**Ändern:**
- `docker/updater/update.sh` — status.json schreiben + trigger-Polling
- `docker-compose.yml` — Volume `update_status` deklarieren, in updater + backend mounten
- `backend/app/config.py` — `github_token`, `github_repo` Settings
- `backend/app/api/routes/admin.py` — zwei neue Endpoints
- `frontend/src/routes/admin/+page.svelte` — Tab "System" + Update-UI

---

## Fehlerszenarien

| Szenario | Verhalten |
|----------|-----------|
| GitHub API nicht erreichbar | `github_reachable: false`, Button disabled, Info-Text im Frontend |
| `status.json` fehlt (erster Start) | `deployed_sha: null`, Badge zeigt "Unbekannt" |
| Trigger-Datei bereits vorhanden | HTTP 409, Frontend zeigt "Update läuft bereits" |
| Deploy schlägt fehl (updater-Log) | `status.json` wird nicht aktualisiert → Polling-Timeout im Frontend |
| Rate-Limit ohne Token (60/h) | Bei 403/429 von GitHub: `github_reachable: false` |

---

## Was nicht in scope ist

- Push-Notifications / WebSocket für automatische Updates im Frontend
- Rollback-Funktion
- Changelog-Anzeige
- E-Mail bei verfügbarem Update
