# ConvoyPlan — Claude Instructions

## Repos

Dieses Projekt besteht aus zwei Git-Repositories:

| Repo | Pfad | Zweck |
|---|---|---|
| **ConvoyPlan** (dieses Repo) | `/Users/working_chris/github/MarschPlan` | App (Backend, Frontend, Docker) |
| **convoyplan-website** | `/Users/working_chris/github/convoyplan-website` | Marketingsite (Astro, SFTP-Deploy) |

## Installer-Scripts synchron halten

Die Installer-Scripts liegen im ConvoyPlan-Repo als Quelle der Wahrheit:

- `scripts/install.sh` — Linux-Installer
- `scripts/install.ps1` — Windows-Installer

Sie werden identisch in der Website unter `public/` gehostet, damit `https://convoyplan.de/install.sh` und `https://convoyplan.de/install.ps1` funktionieren.

**Immer wenn `scripts/install.sh` oder `scripts/install.ps1` geändert werden, müssen die Dateien ins Website-Repo kopiert und dort committed werden:**

```bash
cp /Users/working_chris/github/MarschPlan/scripts/install.sh \
   /Users/working_chris/github/convoyplan-website/public/install.sh

cp /Users/working_chris/github/MarschPlan/scripts/install.ps1 \
   /Users/working_chris/github/convoyplan-website/public/install.ps1

cd /Users/working_chris/github/convoyplan-website
git add public/install.sh public/install.ps1
git commit -m "chore: sync installer scripts from ConvoyPlan repo"
```

Danach muss die Website per SFTP deployt werden (wie üblich).

## Deployment

- **App (ConvoyPlan):** Docker Compose / Portainer auf `s-lx04-docker` (192.168.178.18)
- **Website (convoyplan-website):** Statisches Astro-Build, Deploy per SFTP
