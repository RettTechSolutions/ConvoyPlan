# ConvoyPlan — Claude Instructions

## Repos

| Repo | Zweck |
|---|---|
| **ConvoyPlan** (dieses Repo) — https://github.com/RettTechSolutions/ConvoyPlan | App (Backend, Frontend, Docker) |
| **convoyplan-website** — https://github.com/RettTechSolutions/convoyplan-website | Marketingsite (Astro) |

Weitere, nicht-öffentliche Repos und die Zuordnung lokaler Arbeitskopien stehen
in `CLAUDE.local.md` (nicht eingecheckt, siehe `.gitignore`).

## Installer-Scripts

`scripts/install.sh` (Linux) und `scripts/install.ps1` (Windows) sind die Quelle
der Wahrheit für die Installation. `https://convoyplan.de/install.sh` und
`https://convoyplan.de/install.ps1` sind Weiterleitungen auf die Raw-Dateien aus
diesem Repo — eine Änderung hier ist nach dem Push auf `main` sofort wirksam,
ein Sync in ein anderes Repo ist nicht nötig.

Die Weiterleitungen selbst liegen im Website-Repo; ihre Einrichtung ist in
`.github/repo-setup-checklist.md` beschrieben und nur für Maintainer relevant.

## Deployment

Die Produktivinstanz läuft über Docker Compose (`docker-compose.yml`); der
Updater in `docker/updater/` rollt neue Images aus. Die Marketingsite wird aus
dem Website-Repo heraus als statisches Astro-Build deployt.

### API-Docs (Swagger/OpenAPI)

`/docs`, `/redoc` und `/openapi.json` sind in Produktion **standardmäßig deaktiviert**
(404). Eine extern erreichbare Instanz sollte sie **per API-Key** absichern statt
offen zu schalten:

- **`DOCS_API_KEY=<geheim>`** (empfohlen): Docs sind erreichbar, aber geschützt.
  Der Browser-Einstieg läuft über `/docs`, das ohne gültiges Cookie ein
  Anmeldeformular zeigt; nach erfolgreicher Eingabe merkt ein HttpOnly-Cookie
  die Freigabe. Programmatischer Zugriff via Header `X-API-Key: <geheim>`.
- **`ENABLE_DOCS=true`**: Docs offen erreichbar (ohne Key) — nur für Dev/intern.

Siehe `backend/app/config.py` (`docs_api_key`, `enable_docs`) und
`backend/app/main.py`.

### MCP-Server (KI-Schnittstelle)

`/mcp` stellt Konvois, Fahrzeuge, Wegpunkte, Routen und Status als
Model-Context-Protocol-Server bereit. **Standardmäßig aus** — abgeschaltet wird
kein Endpunkt montiert, auch keine Well-Known-Dokumente.

Der Schalter sitzt im Admin-Portal unter **System → KI-Schnittstelle** und wirkt
ohne Neustart; `MCP_ENABLED` ist nur noch der Ausgangswert (Datenbank schlägt
Umgebung, `app/services/mcp_config.py`). Er *entfernt* die Routen, statt sie mit
404 zu bedecken — `app/mcp/mount.py` trennt dafür Bauen (`mount`) von Anhängen
(`aktivieren`/`deaktivieren`). `tests/test_mcp_toggle.py` prüft die Routentabelle
selbst, nicht nur den Statuscode; wer daran etwas ändert, sieht zuerst dort nach.

Die Instanz ist dabei Resource Server *und* OAuth-2.1-Authorization-Server; Zugriff
entsteht erst durch die Zustimmung eines angemeldeten Benutzers auf `/oauth/consent`
und gilt für genau eine Organisation, gedeckelt durch dessen Rolle. Kein Werkzeug
löscht Daten. Jeder schreibende Aufruf landet im Audit-Log mit Quelle `mcp`.

Code in `backend/app/mcp/` (Werkzeuge, Scopes, Montage), `backend/app/services/
oauth_provider.py` und `oauth_tokens.py`. Verwaltung im Admin-Portal unter **MCP**.
Anwenderdoku: `wiki/MCP-Server.md`.

Die ASGI-Verdrahtung in `app/mcp/mount.py` hängt an internen Details des SDK —
`mcp` ist deshalb exakt gepinnt, und `tests/test_mcp_auth.py` prüft das beobachtbare
Verhalten. Bei einem SDK-Upgrade zuerst dort nachsehen.

## Test-Konventionen

Was in `.github/workflows/ci.yml` blockierend läuft, ist die verbindliche Liste:

- **Backend** — `ruff check app/` und `pytest tests/` (`backend/`). Tests sind
  `async` (`asyncio_mode = "auto"`), sprechen die App über
  `AsyncClient(transport=ASGITransport(app=app))` an und brauchen eine
  PostGIS-Datenbank (`DATABASE_URL`). Autouse-Fixtures in `tests/conftest.py`
  schalten Rate-Limiting, HIBP-Abfrage und Update-Check ab; ein Test, der genau
  das prüft, aktiviert es selbst wieder.
- **Frontend** — `npm run check` (svelte-check) in `frontend/`.
- **Shell** — die Suiten unter `docker/updater/tests/` und für den
  GraphHopper-Entrypoint; sie tragen den Regionswechsel und laufen im Job
  `Shell – Updater und Entrypoint`.
- **Container** — Trivy scannt alle fünf Images (`backend`, `frontend`,
  `graphhopper`, `updater`, `osmium`) auf HIGH/CRITICAL mit verfügbarem Fix.
  Ausnahmen gehören mit Begründung in `.trivyignore`.

Neue Tests liegen neben den bestehenden in `backend/tests/` und werden nach dem
geprüften Verhalten benannt (`test_<thema>.py`), nicht nach der Implementierung.
