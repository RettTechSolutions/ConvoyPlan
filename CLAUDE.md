# ConvoyPlan — Claude Instructions

## Repos

Dieses Projekt besteht aus zwei Git-Repositories:

| Repo | Pfad | Zweck |
|---|---|---|
| **ConvoyPlan** (dieses Repo) | `[/Users/working_chris/github/ConvoyPlan](https://github.com/RettTechSolutions/ConvoyPlan)` | App (Backend, Frontend, Docker) |
| **convoyplan-website** | `[/Users/working_chris/github/convoyplan-website](https://github.com/RettTechSolutions/convoyplan-website)` | Marketingsite (Astro, Cloudflare-Deploy) |
| **convoyplan-Lizenzmanager** | `[/Users/working_chris/github/convoyplan-website](https://github.com/RettTechSolutions/ConvoyPlan-Lizenzmanager)` | Lizenztool zur Lizenz Erstellung anhand der UUID die während der Installation generiert wird  |
| **convoyplan-Documentation** | `[/Users/working_chris/github/convoyplan-website](https://github.com/RettTechSolutions/ConvoyPlan-Documentation)` | Umfassende Dokumentation mit Wiki |


## Installer-Scripts

Die Installer-Scripts liegen im ConvoyPlan-Repo als Quelle der Wahrheit:

- `scripts/install.sh` — Linux-Installer
- `scripts/install.ps1` — Windows-Installer

`https://convoyplan.de/install.sh` und `https://convoyplan.de/install.ps1` sind **HTTP-302-Weiterleitungen** (via `public/_redirects` im Website-Repo) auf die Raw-GitHub-URLs:

```
https://raw.githubusercontent.com/RettTechSolutions/ConvoyPlan/main/scripts/install.sh
https://raw.githubusercontent.com/RettTechSolutions/ConvoyPlan/main/scripts/install.ps1
```

**Kein Sync nötig** — Änderungen in `scripts/install.sh` oder `scripts/install.ps1` sind sofort nach dem Push auf `main` über convoyplan.de erreichbar.

Nur wenn sich Repo-Name, Branch oder Dateipfad ändern: `public/_redirects` im Website-Repo aktualisieren und deployen.

## Deployment

- **App (ConvoyPlan):** Produktiv auf **`web.convoyplan.de`** (extern erreichbar). Docker Compose.
- **Website (convoyplan-website):** Statisches Astro-Build auf **Cloudflare** (Workers Static Assets
  via `@astrojs/cloudflare`), Deploy über die Git-Integration von Cloudflare Workers Builds.
  Der frühere SFTP-Deploy auf Webspace bei united-domains ist entfallen, ebenso die
  `public/.htaccess` — Weiterleitungen liegen jetzt in `public/_redirects`, Header in
  `public/_headers`. Details im CLAUDE.md des Website-Repos.

### API-Docs (Swagger/OpenAPI)

`/docs`, `/redoc` und `/openapi.json` sind in Produktion **standardmäßig deaktiviert** (404).
Da `web.convoyplan.de` extern erreichbar ist, werden sie **bevorzugt per API-Key** abgesichert
statt offen aktiviert:

- **`DOCS_API_KEY=<geheim>`** (empfohlen): Docs sind erreichbar, aber geschützt.
  Der Browser-Einstieg läuft über `/docs`, das ohne gültiges Cookie ein
  Anmeldeformular zeigt; nach erfolgreicher Eingabe merkt ein HttpOnly-Cookie
  die Freigabe. Programmatischer Zugriff via Header `X-API-Key: <geheim>`.
- **`ENABLE_DOCS=true`**: Docs offen erreichbar (ohne Key) — nur für Dev/intern.

Ein `?key=…` im Query-String wird nicht akzeptiert. Siehe `backend/app/api/docs_ui.py`
(Türsteher, Formular, Cookie) und `backend/app/config.py` (`docs_api_key`, `enable_docs`).

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
