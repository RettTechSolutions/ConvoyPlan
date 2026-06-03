# ConvoyPlan — Claude Instructions

## Repos

Dieses Projekt besteht aus zwei Git-Repositories:

| Repo | Pfad | Zweck |
|---|---|---|
| **ConvoyPlan** (dieses Repo) | `/Users/working_chris/github/MarschPlan` | App (Backend, Frontend, Docker) |
| **convoyplan-website** | `/Users/working_chris/github/convoyplan-website` | Marketingsite (Astro, SFTP-Deploy) |

## Installer-Scripts

Die Installer-Scripts liegen im ConvoyPlan-Repo als Quelle der Wahrheit:

- `scripts/install.sh` — Linux-Installer
- `scripts/install.ps1` — Windows-Installer

`https://convoyplan.de/install.sh` und `https://convoyplan.de/install.ps1` sind **HTTP-302-Weiterleitungen** (via `public/.htaccess` im Website-Repo) auf die Raw-GitHub-URLs:

```
https://raw.githubusercontent.com/RettTechSolutions/ConvoyPlan/main/scripts/install.sh
https://raw.githubusercontent.com/RettTechSolutions/ConvoyPlan/main/scripts/install.ps1
```

**Kein Sync nötig** — Änderungen in `scripts/install.sh` oder `scripts/install.ps1` sind sofort nach dem Push auf `main` über convoyplan.de erreichbar.

Nur wenn sich Repo-Name, Branch oder Dateipfad ändern: `public/.htaccess` im Website-Repo aktualisieren und per SFTP deployen.

## Deployment

- **App (ConvoyPlan):** Produktiv auf **`web.convoyplan.de`** (extern erreichbar). Docker Compose / Portainer.
  - _Hinweis:_ Früher lief die App intern auf `s-lx04-docker` (192.168.178.18) — das ist **nicht mehr aktuell**.
- **Website (convoyplan-website):** Statisches Astro-Build, Deploy per SFTP

### API-Docs (Swagger/OpenAPI)

`/docs`, `/redoc` und `/openapi.json` sind in Produktion **standardmäßig deaktiviert** (404),
damit die API-Oberfläche nicht öffentlich offenliegt. Da `web.convoyplan.de` extern erreichbar
ist, bewusst aktivieren mit `ENABLE_DOCS=true` in der Umgebung (Docker Compose/Portainer) —
idealerweise hinter Reverse-Proxy-Auth oder IP-Beschränkung. Siehe `backend/app/config.py`
(`enable_docs`) und `backend/app/main.py`.
