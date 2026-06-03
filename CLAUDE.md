# ConvoyPlan — Claude Instructions

## Repos

Dieses Projekt besteht aus zwei Git-Repositories:

| Repo | Pfad | Zweck |
|---|---|---|
| **ConvoyPlan** (dieses Repo) | `[/Users/working_chris/github/ConvoyPlan](https://github.com/RettTechSolutions/ConvoyPlan)` | App (Backend, Frontend, Docker) |
| **convoyplan-website** | `[/Users/working_chris/github/convoyplan-website](https://github.com/RettTechSolutions/convoyplan-website)` | Marketingsite (Astro, SFTP-Deploy) |
| **convoyplan-Lizenzmanager** | `[/Users/working_chris/github/convoyplan-website](https://github.com/RettTechSolutions/ConvoyPlan-Lizenzmanager)` | Lizenztool zur Lizenz Erstellung anhand der UUID die während der Installation generiert wird  |
| **convoyplan-Documentation** | `[/Users/working_chris/github/convoyplan-website](https://github.com/RettTechSolutions/ConvoyPlan-Documentation)` | Umfassende Dokumentation mit Wiki |


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

- **App (ConvoyPlan):** Docker Compose  auf `web.convoyplan.de`
- **Website (convoyplan-website):** Statisches Astro-Build, Deploy per SFTP auf `convoyplan.de`
