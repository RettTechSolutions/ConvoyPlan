# Installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Interaktiver One-Command-Installer für Linux (`install.sh`) und Windows (`install.ps1`), aufrufbar über `https://convoyplan.de/install.sh` — fragt Domain, E-Mail, Passwort und OSM-Region ab, generiert `.env` und startet den Stack.

**Architecture:** Die Scripts liegen in `scripts/` im ConvoyPlan-Repo und werden identisch in `public/` der Astro-Website abgelegt (statisches Hosting, kein dynamischer Redirect möglich). Die Website liefert sie direkt per HTTPS aus. Zusätzlich wird `portainer-stack.yml` um fehlende Env-Variablen ergänzt.

**Tech Stack:** Bash (`set -euo pipefail`), PowerShell 5.1+, Docker Compose, Astro (static output, SFTP-Deploy)

---

## File Map

| Datei | Aktion |
|---|---|
| `portainer-stack.yml` | Modify — `LICENSE_KEY`, `GITHUB_TOKEN`, `GITHUB_REPO` im Backend; `logo_uploads`-Volume |
| `scripts/install.sh` | Create — Linux-Installer |
| `scripts/install.ps1` | Create — Windows-Installer |
| `convoyplan-website/public/install.sh` | Create — Kopie von `scripts/install.sh` (statisch gehostet) |
| `convoyplan-website/public/install.ps1` | Create — Kopie von `scripts/install.ps1` (statisch gehostet) |
| `README.md` | Modify — Quickstart-Abschnitt um Installer-Einzeiler ergänzen |

---

## Task 1: portainer-stack.yml — fehlende Env-Variablen und Volumes

**Files:**
- Modify: `portainer-stack.yml`

- [ ] **Step 1: Backend-Environment um Lizenz- und Updater-Variablen ergänzen**

In `portainer-stack.yml`, den `backend`-Service-Block `environment`-Abschnitt ersetzen:

```yaml
  backend:
    image: ${BACKEND_IMAGE:-convoyplan-backend:latest}
    restart: unless-stopped
    command: sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-convoyplan}:${POSTGRES_PASSWORD:-convoyplan}@db:5432/${POSTGRES_DB:-convoyplan}
      JWT_SECRET: ${JWT_SECRET:-changeme-in-production}
      GRAPHHOPPER_URL: http://graphhopper:8989
      LICENSE_KEY: ${LICENSE_KEY:-}
      GITHUB_TOKEN: ${GITHUB_TOKEN:-}
      GITHUB_REPO: ${GITHUB_REPO:-RettTechSolutions/ConvoyPlan}
    volumes:
      - cert_uploads:/certs
      - logo_uploads:/uploads
```

- [ ] **Step 2: `logo_uploads`-Volume in der Volumes-Sektion ergänzen**

Die `volumes:`-Sektion am Ende der Datei:

```yaml
volumes:
  postgres_data:
  osm_data:
  gh_graph:
  caddy_data:
  caddy_config:
  cert_uploads:
  logo_uploads:
```

- [ ] **Step 3: Smoke-Test**

```bash
cd /Users/working_chris/github/MarschPlan
grep "LICENSE_KEY" portainer-stack.yml
grep "logo_uploads" portainer-stack.yml
```

Erwartete Ausgabe: Beide Zeilen werden gefunden.

- [ ] **Step 4: Commit**

```bash
git add portainer-stack.yml
git commit -m "fix: add LICENSE_KEY, GITHUB_TOKEN, GITHUB_REPO and logo_uploads to portainer-stack.yml"
```

---

## Task 2: scripts/install.sh — Linux-Installer

**Files:**
- Create: `scripts/install.sh`

- [ ] **Step 1: Script erstellen**

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/RettTechSolutions/ConvoyPlan/main"
STACK_URL="$REPO_RAW/portainer-stack.yml"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║      ConvoyPlan Installer v0.5           ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Voraussetzungen prüfen
if ! command -v docker &>/dev/null; then
  echo "FEHLER: 'docker' nicht gefunden."
  echo "       Installieren: https://docs.docker.com/engine/install/"
  exit 1
fi
if ! docker compose version &>/dev/null 2>&1; then
  echo "FEHLER: Docker Compose Plugin nicht gefunden."
  echo "       Installieren: https://docs.docker.com/compose/install/"
  exit 1
fi
if ! docker info &>/dev/null 2>&1; then
  echo "FEHLER: Docker-Daemon nicht erreichbar. Docker starten und erneut versuchen."
  exit 1
fi
echo "✓ Docker und Docker Compose gefunden"
echo ""

# Hilfsfunktionen
prompt() {
  local msg="$1" default="$2" varname="$3"
  local val
  if [[ -n "$default" ]]; then
    read -rp "$msg [$default]: " val
    printf -v "$varname" '%s' "${val:-$default}"
  else
    while true; do
      read -rp "$msg: " val
      [[ -n "$val" ]] && break
      echo "  Dieses Feld ist Pflicht."
    done
    printf -v "$varname" '%s' "$val"
  fi
}

prompt_secret() {
  local msg="$1" varname="$2"
  local val1 val2
  while true; do
    read -rsp "$msg: " val1; echo
    read -rsp "Passwort bestätigen: " val2; echo
    if [[ -n "$val1" && "$val1" == "$val2" ]]; then
      printf -v "$varname" '%s' "$val1"
      break
    fi
    echo "  Passwörter stimmen nicht überein oder leer. Erneut versuchen."
  done
}

# Eingaben
prompt "Installationsverzeichnis" "$HOME/convoyplan" INSTALL_DIR
prompt "Domain (z.B. convoy.example.com)" "" DOMAIN
prompt "E-Mail für Let's Encrypt" "" ACME_EMAIL
prompt_secret "Datenbankpasswort" DB_PASSWORD

echo ""
echo "OSM-Region wählen:"
echo "  1) Deutschland (~4 GB)"
echo "  2) Bayern      (~1 GB)"
echo "  3) Berlin      (~30 MB, für Tests)"
echo "  4) Eigene URL eingeben"
read -rp "Auswahl [1]: " OSM_CHOICE
OSM_CHOICE="${OSM_CHOICE:-1}"

case "$OSM_CHOICE" in
  1) OSM_URL="https://download.geofabrik.de/europe/germany-latest.osm.pbf"
     OSM_FILE="germany-latest.osm.pbf" ;;
  2) OSM_URL="https://download.geofabrik.de/europe/germany/bayern-latest.osm.pbf"
     OSM_FILE="bayern-latest.osm.pbf" ;;
  3) OSM_URL="https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf"
     OSM_FILE="berlin-latest.osm.pbf" ;;
  4) prompt "OSM-Download-URL" "" OSM_URL
     OSM_FILE="$(basename "$OSM_URL")" ;;
  *) echo "FEHLER: Ungültige Auswahl '$OSM_CHOICE'."; exit 1 ;;
esac

read -rp "Lizenzschlüssel [Enter = Demo-Modus]: " LICENSE_KEY || true
read -rp "GitHub Token für Auto-Updater [Enter = überspringen]: " GITHUB_TOKEN || true

# JWT_SECRET generieren
JWT_SECRET="$(openssl rand -hex 32)"

# Installationsverzeichnis anlegen
if [[ -d "$INSTALL_DIR" && -f "$INSTALL_DIR/.env" ]]; then
  read -rp "Verzeichnis '$INSTALL_DIR' mit .env existiert. Überschreiben? [j/N]: " OVERWRITE || true
  if [[ "${OVERWRITE,,}" != "j" ]]; then
    echo "Abgebrochen."
    exit 0
  fi
fi
mkdir -p "$INSTALL_DIR"

# Stack-Datei herunterladen
echo ""
echo "→ Stack-Konfiguration herunterladen..."
curl -sSL "$STACK_URL" -o "$INSTALL_DIR/docker-compose.yml"

# .env schreiben
cat > "$INSTALL_DIR/.env" <<ENVEOF
POSTGRES_USER=convoyplan
POSTGRES_PASSWORD=${DB_PASSWORD}
POSTGRES_DB=convoyplan
JWT_SECRET=${JWT_SECRET}
DOMAIN=${DOMAIN}
ACME_EMAIL=${ACME_EMAIL}
HTTP_PORT=80
HTTPS_PORT=443
OSM_DOWNLOAD_URL=${OSM_URL}
OSM_FILENAME=${OSM_FILE}
JAVA_OPTS=-Xmx2g -Xms512m -XX:+UseG1GC
BACKEND_IMAGE=ghcr.io/retttechsolutions/convoyplan-backend:latest
FRONTEND_IMAGE=ghcr.io/retttechsolutions/convoyplan-frontend:latest
GRAPHHOPPER_IMAGE=ghcr.io/retttechsolutions/convoyplan-graphhopper:latest
GITHUB_REPO=RettTechSolutions/ConvoyPlan
ENVEOF

[[ -n "${LICENSE_KEY:-}" ]] && echo "LICENSE_KEY=${LICENSE_KEY}" >> "$INSTALL_DIR/.env"
[[ -n "${GITHUB_TOKEN:-}" ]] && echo "GITHUB_TOKEN=${GITHUB_TOKEN}" >> "$INSTALL_DIR/.env"

# Stack starten
cd "$INSTALL_DIR"
echo ""
echo "→ Images herunterladen (kann einige Minuten dauern)..."
docker compose pull

echo ""
echo "→ ConvoyPlan starten..."
docker compose up -d

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ConvoyPlan läuft!                                       ║"
printf "║  Setup-Wizard: https://%-34s║\n" "${DOMAIN}/setup"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
```

- [ ] **Step 2: Ausführbar machen**

```bash
chmod +x /Users/working_chris/github/MarschPlan/scripts/install.sh
```

- [ ] **Step 3: Syntax-Check**

```bash
bash -n /Users/working_chris/github/MarschPlan/scripts/install.sh
```

Erwartete Ausgabe: keine Fehler, Exit-Code 0.

- [ ] **Step 4: Dry-Run Smoke-Test (ohne Docker)**

Prüfen ob das Script korrekt abbricht wenn Docker fehlt:

```bash
# PATH ohne docker — simuliert fehlende Abhängigkeit
PATH=/usr/bin:/bin bash /Users/working_chris/github/MarschPlan/scripts/install.sh 2>&1 | head -5
```

Erwartete Ausgabe enthält: `FEHLER: 'docker' nicht gefunden.`

- [ ] **Step 5: Commit**

```bash
git add scripts/install.sh
git commit -m "feat: add Linux installer script (install.sh)"
```

---

## Task 3: scripts/install.ps1 — Windows-Installer

**Files:**
- Create: `scripts/install.ps1`

- [ ] **Step 1: Script erstellen**

```powershell
#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRaw  = 'https://raw.githubusercontent.com/RettTechSolutions/ConvoyPlan/main'
$StackUrl = "$RepoRaw/portainer-stack.yml"

Write-Host ''
Write-Host '╔══════════════════════════════════════════╗' -ForegroundColor Cyan
Write-Host '║      ConvoyPlan Installer v0.5           ║' -ForegroundColor Cyan
Write-Host '╚══════════════════════════════════════════╝' -ForegroundColor Cyan
Write-Host ''

# Voraussetzungen prüfen
function Test-DockerAvailable {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host 'FEHLER: docker nicht gefunden.' -ForegroundColor Red
        Write-Host '       Installieren: https://docs.docker.com/desktop/windows/' -ForegroundColor Red
        exit 1
    }
    try { docker compose version 2>&1 | Out-Null } catch {
        Write-Host 'FEHLER: Docker Compose Plugin nicht gefunden.' -ForegroundColor Red
        exit 1
    }
    try { docker info 2>&1 | Out-Null } catch {
        Write-Host 'FEHLER: Docker laeuft nicht. Docker Desktop starten.' -ForegroundColor Red
        exit 1
    }
    Write-Host '✓ Docker und Docker Compose gefunden' -ForegroundColor Green
}
Test-DockerAvailable
Write-Host ''

# Hilfsfunktionen
function Read-Input {
    param([string]$Prompt, [string]$Default = '')
    if ($Default) {
        $val = Read-Host "$Prompt [$Default]"
        if (-not $val) { return $Default }
        return $val
    }
    do {
        $val = Read-Host $Prompt
        if (-not $val) { Write-Host '  Dieses Feld ist Pflicht.' -ForegroundColor Yellow }
    } while (-not $val)
    return $val
}

function Read-ConfirmedPassword {
    param([string]$Prompt)
    while ($true) {
        $s1 = Read-Host $Prompt -AsSecureString
        $s2 = Read-Host 'Passwort bestaetigen' -AsSecureString
        $p1 = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
              [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s1))
        $p2 = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
              [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s2))
        if ($p1 -and $p1 -eq $p2) { return $p1 }
        Write-Host '  Passwoerter stimmen nicht ueberein oder leer.' -ForegroundColor Yellow
    }
}

# Eingaben
$InstallDir  = Read-Input 'Installationsverzeichnis' (Join-Path $env:USERPROFILE 'convoyplan')
$Domain      = Read-Input 'Domain (z.B. convoy.example.com)'
$AcmeEmail   = Read-Input 'E-Mail fuer Lets Encrypt'
$DbPassword  = Read-ConfirmedPassword 'Datenbankpasswort'

Write-Host ''
Write-Host 'OSM-Region waehlen:'
Write-Host '  1) Deutschland (~4 GB)'
Write-Host '  2) Bayern      (~1 GB)'
Write-Host '  3) Berlin      (~30 MB, fuer Tests)'
Write-Host '  4) Eigene URL eingeben'
$OsmChoice = Read-Host 'Auswahl [1]'
if (-not $OsmChoice) { $OsmChoice = '1' }

switch ($OsmChoice) {
    '1' { $OsmUrl  = 'https://download.geofabrik.de/europe/germany-latest.osm.pbf'
          $OsmFile = 'germany-latest.osm.pbf' }
    '2' { $OsmUrl  = 'https://download.geofabrik.de/europe/germany/bayern-latest.osm.pbf'
          $OsmFile = 'bayern-latest.osm.pbf' }
    '3' { $OsmUrl  = 'https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf'
          $OsmFile = 'berlin-latest.osm.pbf' }
    '4' { $OsmUrl  = Read-Input 'OSM-Download-URL'
          $OsmFile = [IO.Path]::GetFileName($OsmUrl) }
    default { Write-Host "FEHLER: Ungueltige Auswahl '$OsmChoice'." -ForegroundColor Red; exit 1 }
}

$LicenseKey   = Read-Host 'Lizenzschluessel [Enter = Demo-Modus]'
$GithubToken  = Read-Host 'GitHub Token fuer Auto-Updater [Enter = ueberspringen]'

# JWT_SECRET generieren
$Rng   = [Security.Cryptography.RandomNumberGenerator]::Create()
$Bytes = New-Object byte[] 32
$Rng.GetBytes($Bytes)
$JwtSecret = ($Bytes | ForEach-Object { $_.ToString('x2') }) -join ''

# Installationsverzeichnis anlegen
if ((Test-Path $InstallDir) -and (Test-Path (Join-Path $InstallDir '.env'))) {
    $overwrite = Read-Host "Verzeichnis '$InstallDir' mit .env existiert. Ueberschreiben? [j/N]"
    if ($overwrite -ne 'j') { Write-Host 'Abgebrochen.'; exit 0 }
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# Stack-Datei herunterladen
Write-Host ''
Write-Host '-> Stack-Konfiguration herunterladen...'
Invoke-WebRequest -Uri $StackUrl -OutFile (Join-Path $InstallDir 'docker-compose.yml') -UseBasicParsing

# .env schreiben
$EnvContent = @"
POSTGRES_USER=convoyplan
POSTGRES_PASSWORD=$DbPassword
POSTGRES_DB=convoyplan
JWT_SECRET=$JwtSecret
DOMAIN=$Domain
ACME_EMAIL=$AcmeEmail
HTTP_PORT=80
HTTPS_PORT=443
OSM_DOWNLOAD_URL=$OsmUrl
OSM_FILENAME=$OsmFile
JAVA_OPTS=-Xmx2g -Xms512m -XX:+UseG1GC
BACKEND_IMAGE=ghcr.io/retttechsolutions/convoyplan-backend:latest
FRONTEND_IMAGE=ghcr.io/retttechsolutions/convoyplan-frontend:latest
GRAPHHOPPER_IMAGE=ghcr.io/retttechsolutions/convoyplan-graphhopper:latest
GITHUB_REPO=RettTechSolutions/ConvoyPlan
"@
if ($LicenseKey)  { $EnvContent += "`nLICENSE_KEY=$LicenseKey" }
if ($GithubToken) { $EnvContent += "`nGITHUB_TOKEN=$GithubToken" }

Set-Content -Path (Join-Path $InstallDir '.env') -Value $EnvContent -Encoding UTF8

# Stack starten
Push-Location $InstallDir
try {
    Write-Host ''
    Write-Host '-> Images herunterladen (kann einige Minuten dauern)...'
    docker compose pull
    Write-Host ''
    Write-Host '-> ConvoyPlan starten...'
    docker compose up -d
} finally {
    Pop-Location
}

Write-Host ''
Write-Host '╔══════════════════════════════════════════════════════════╗' -ForegroundColor Green
Write-Host '║  ConvoyPlan laeuft!                                      ║' -ForegroundColor Green
Write-Host "║  Setup-Wizard: https://$Domain/setup" -ForegroundColor Green
Write-Host '╚══════════════════════════════════════════════════════════╝' -ForegroundColor Green
Write-Host ''
```

- [ ] **Step 2: Syntax-Check**

```powershell
# PowerShell-Syntaxcheck ohne Ausführung
$null = [System.Management.Automation.Language.Parser]::ParseFile(
    '/Users/working_chris/github/MarschPlan/scripts/install.ps1', [ref]$null, [ref]$null
)
Write-Host 'Syntax OK'
```

Alternativ auf macOS/Linux:

```bash
pwsh -NoProfile -NonInteractive -Command "
  \$errors = \$null
  \$null = [System.Management.Automation.Language.Parser]::ParseFile(
    '/Users/working_chris/github/MarschPlan/scripts/install.ps1', [ref]\$null, [ref]\$errors
  )
  if (\$errors) { \$errors; exit 1 } else { 'Syntax OK' }
"
```

Erwartete Ausgabe: `Syntax OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/install.ps1
git commit -m "feat: add Windows installer script (install.ps1)"
```

---

## Task 4: Astro-Website — Scripts in public/ ablegen

**Files:**
- Create: `convoyplan-website/public/install.sh`
- Create: `convoyplan-website/public/install.ps1`

Die Website hat `output: 'static'` — Dateien in `public/` werden 1:1 ausgeliefert.

- [ ] **Step 1: install.sh in public/ kopieren**

```bash
cp /Users/working_chris/github/MarschPlan/scripts/install.sh \
   /Users/working_chris/github/convoyplan-website/public/install.sh
```

- [ ] **Step 2: install.ps1 in public/ kopieren**

```bash
cp /Users/working_chris/github/MarschPlan/scripts/install.ps1 \
   /Users/working_chris/github/convoyplan-website/public/install.ps1
```

- [ ] **Step 3: Prüfen ob die Dateien korrekt landen**

```bash
ls -la /Users/working_chris/github/convoyplan-website/public/install.*
head -3 /Users/working_chris/github/convoyplan-website/public/install.sh
```

Erwartete Ausgabe: Beide Dateien vorhanden, erste Zeile `#!/usr/bin/env bash`.

- [ ] **Step 4: Commit in Website-Repo**

```bash
cd /Users/working_chris/github/convoyplan-website
git add public/install.sh public/install.ps1
git commit -m "feat: add install.sh and install.ps1 for one-command installer"
```

---

## Task 5: README — Quickstart um Installer-Einzeiler erweitern

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Neuen Abschnitt vor dem bisherigen Quickstart einfügen**

Den Abschnitt `## Quickstart` so anpassen, dass ganz oben eine „Schnellinstallation" steht und der bisherige Entwickler-Quickstart darunter bleibt:

```markdown
## Quickstart

### Schnellinstallation (empfohlen)

**Linux:**

```bash
curl -sSL https://convoyplan.de/install.sh | bash
```

**Windows (PowerShell als Administrator):**

```powershell
irm https://convoyplan.de/install.ps1 | iex
```

Der Installer prüft Voraussetzungen (Docker, Docker Compose), fragt interaktiv nach Domain, E-Mail, Datenbankpasswort und OSM-Region, generiert einen `JWT_SECRET` automatisch und startet den Stack. Nach Abschluss öffnet sich der Setup-Wizard unter `https://<DOMAIN>/setup`.

**Voraussetzungen:** Docker Engine (Linux) oder Docker Desktop (Windows) muss installiert und gestartet sein.

---

### Manuelle Installation (Entwicklung / Portainer)
```

- [ ] **Step 2: Prüfen ob die Änderung korrekt ist**

```bash
grep -A 20 "## Quickstart" /Users/working_chris/github/MarschPlan/README.md | head -25
```

Erwartete Ausgabe: Enthält `curl -sSL https://convoyplan.de/install.sh | bash`.

- [ ] **Step 3: Commit**

```bash
cd /Users/working_chris/github/MarschPlan
git add README.md
git commit -m "docs: add one-command installer to README quickstart"
```

---

## Abschluss: Push und PRs

- [ ] **Step 1: Main-Repo pushen**

```bash
cd /Users/working_chris/github/MarschPlan
git push
```

- [ ] **Step 2: PR für Main-Repo öffnen**

```bash
gh pr create \
  --title "feat: one-command installer (install.sh + install.ps1)" \
  --body "Interaktiver Installer für Linux und Windows. Aufrufbar via convoyplan.de/install.sh und convoyplan.de/install.ps1. Fragt Domain, E-Mail, Passwort, OSM-Region ab — JWT_SECRET wird automatisch generiert. Fixes portainer-stack.yml (fehlende LICENSE_KEY, GITHUB_TOKEN, logo_uploads)."
```

- [ ] **Step 3: Website-Repo pushen und deployen**

```bash
cd /Users/working_chris/github/convoyplan-website
git push
# SFTP-Deploy wie üblich ausführen
```
