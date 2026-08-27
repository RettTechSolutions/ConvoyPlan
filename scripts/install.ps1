#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRaw           = 'https://raw.githubusercontent.com/RettTechSolutions/ConvoyPlan/main'
$StackUrl          = "$RepoRaw/docker-compose.yml"
$CaddyEntrypointUrl = "$RepoRaw/caddy/entrypoint.sh"

Write-Host ''
Write-Host '╔══════════════════════════════════════════╗' -ForegroundColor Cyan
Write-Host '║      ConvoyPlan Installer v0.8.5         ║' -ForegroundColor Cyan
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
$InstallDir = Read-Input 'Installationsverzeichnis' (Join-Path $env:USERPROFILE 'convoyplan')

# ── Bestehende Installation erkennen ─────────────────────────────────────────
function Get-EnvValue {
    param([string]$Key, [string]$File)
    $line = Get-Content $File -ErrorAction SilentlyContinue | Where-Object { $_ -match "^${Key}=" } | Select-Object -First 1
    if ($line) { return $line.Substring($Key.Length + 1) }
    return ''
}

function Add-EnvKeyIfMissing {
    param([string]$Key, [string]$Value, [string]$File)
    $existing = Get-Content $File -ErrorAction SilentlyContinue | Where-Object { $_ -match "^${Key}=" }
    if (-not $existing) {
        Add-Content -Path $File -Value "${Key}=${Value}"
        Write-Host "  + ${Key} ergaenzt" -ForegroundColor DarkGray
    }
}

$EnvFile = Join-Path $InstallDir '.env'
if ((Test-Path $EnvFile)) {
    $existingPw     = Get-EnvValue 'POSTGRES_PASSWORD' $EnvFile
    $existingDomain = Get-EnvValue 'DOMAIN' $EnvFile

    if ($existingPw -and $existingDomain) {
        Write-Host ''
        Write-Host "Bestehende ConvoyPlan-Installation in '$InstallDir' gefunden." -ForegroundColor Cyan
        Write-Host '  [J] Nur aktualisieren - Einstellungen beibehalten  (empfohlen)' -ForegroundColor Green
        Write-Host '  [n] Neu konfigurieren - Werte als Vorauswahl laden'
        $updateChoice = Read-Host 'Auswahl [J/n]'

        if ($updateChoice -ine 'n') {
            # ── UPDATE-MODUS ─────────────────────────────────────────────────
            Write-Host ''
            Write-Host '-> Fehlende Konfigurationseintraege ergaenzen...'
            Add-EnvKeyIfMissing 'STACK_FILE_PATH'       "$InstallDir\docker-compose.yml"                          $EnvFile
            Add-EnvKeyIfMissing 'CADDY_ENTRYPOINT_PATH' "$InstallDir\caddy\entrypoint.sh"                        $EnvFile
            Add-EnvKeyIfMissing 'COMPOSE_PROJECT_NAME'  'convoyplan'                                             $EnvFile
            Add-EnvKeyIfMissing 'UPDATER_IMAGE'         'ghcr.io/retttechsolutions/convoyplan/updater:latest'    $EnvFile
            Add-EnvKeyIfMissing 'BACKEND_IMAGE'         'ghcr.io/retttechsolutions/convoyplan/backend:latest'    $EnvFile
            Add-EnvKeyIfMissing 'FRONTEND_IMAGE'        'ghcr.io/retttechsolutions/convoyplan/frontend:latest'   $EnvFile
            Add-EnvKeyIfMissing 'GRAPHHOPPER_IMAGE'     'ghcr.io/retttechsolutions/convoyplan/graphhopper:latest' $EnvFile
            Add-EnvKeyIfMissing 'GITHUB_REPO'           'RettTechSolutions/ConvoyPlan'                          $EnvFile

            Write-Host ''
            Write-Host '-> Neueste Stack-Konfiguration herunterladen...'
            New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir 'caddy') | Out-Null
            try {
                Invoke-WebRequest -Uri $StackUrl -OutFile (Join-Path $InstallDir 'docker-compose.yml') -UseBasicParsing
            } catch {
                Write-Host 'FEHLER: Stack-Datei konnte nicht heruntergeladen werden.' -ForegroundColor Red; exit 1
            }
            try {
                Invoke-WebRequest -Uri $CaddyEntrypointUrl -OutFile (Join-Path $InstallDir 'caddy\entrypoint.sh') -UseBasicParsing
            } catch {
                Write-Host 'FEHLER: Caddy-Entrypoint konnte nicht heruntergeladen werden.' -ForegroundColor Red; exit 1
            }

            Write-Host ''
            Write-Host '-> Images aktualisieren...'
            docker compose --project-directory $InstallDir pull

            Write-Host ''
            Write-Host '-> ConvoyPlan neu starten...'
            docker compose --project-directory $InstallDir up -d

            Write-Host ''
            Write-Host '╔══════════════════════════════════════════════════════════╗' -ForegroundColor Green
            Write-Host '║  ConvoyPlan wurde aktualisiert!                          ║' -ForegroundColor Green
            Write-Host ("║  URL: https://$existingDomain/").PadRight(61) + "║"      -ForegroundColor Green
            Write-Host '╚══════════════════════════════════════════════════════════╝' -ForegroundColor Green
            Write-Host ''
            exit 0
        }

        # ── NEU-KONFIGURIEREN mit bestehenden Werten als Vorauswahl ─────────
        Write-Host ''
        Write-Host '✓ Bestehende Werte als Vorauswahl geladen.'
        $Domain     = Read-Input 'Domain (z.B. convoy.example.com)' (Get-EnvValue 'DOMAIN' $EnvFile)
        $AcmeEmail  = Read-Input 'E-Mail fuer Lets Encrypt'         (Get-EnvValue 'ACME_EMAIL' $EnvFile)
        $prevPw     = Get-EnvValue 'POSTGRES_PASSWORD' $EnvFile
        Write-Host "Datenbankpasswort [Enter = bestehendes beibehalten]: " -NoNewline
        $s1 = Read-Host -AsSecureString
        $typed = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                 [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s1))
        $DbPassword = if ($typed) { $typed } else { $prevPw }
    } else {
        # Unvollstaendige .env — normale Abfrage mit Vorauswahl
        $Domain    = Read-Input 'Domain (z.B. convoy.example.com)' (Get-EnvValue 'DOMAIN' $EnvFile)
        $AcmeEmail = Read-Input 'E-Mail fuer Lets Encrypt'         (Get-EnvValue 'ACME_EMAIL' $EnvFile)
        $DbPassword = Read-ConfirmedPassword 'Datenbankpasswort'
    }
} else {
    $Domain     = Read-Input 'Domain (z.B. convoy.example.com)'
    $AcmeEmail  = Read-Input 'E-Mail fuer Lets Encrypt'
    $DbPassword = Read-ConfirmedPassword 'Datenbankpasswort'
}

Write-Host ''
Write-Host 'OSM-Region waehlen:'
Write-Host '  1) DACH: DE+AT+CH+LI (~5,5 GB)'
Write-Host '  2) Deutschland       (~4 GB)'
Write-Host '  3) Bayern            (~1 GB)'
Write-Host '  4) Berlin            (~30 MB, fuer Tests)'
Write-Host '  5) Eigene URL eingeben'
$OsmChoice = Read-Host 'Auswahl [1]'
if (-not $OsmChoice) { $OsmChoice = '1' }

# JAVA_OPTS scale with the region's PBF size — must match install.sh, otherwise
# the DACH default OOMs on a 2 GB heap during the graph import.
switch ($OsmChoice) {
    '1' { $OsmUrl  = 'https://download.geofabrik.de/europe/dach-latest.osm.pbf'
          $OsmFile = 'dach-latest.osm.pbf'
          $JavaOpts = '-Xmx8g -Xms1g -XX:+UseG1GC' }
    '2' { $OsmUrl  = 'https://download.geofabrik.de/europe/germany-latest.osm.pbf'
          $OsmFile = 'germany-latest.osm.pbf'
          $JavaOpts = '-Xmx6g -Xms1g -XX:+UseG1GC' }
    '3' { $OsmUrl  = 'https://download.geofabrik.de/europe/germany/bayern-latest.osm.pbf'
          $OsmFile = 'bayern-latest.osm.pbf'
          $JavaOpts = '-Xmx3g -Xms512m -XX:+UseG1GC' }
    '4' { $OsmUrl  = 'https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf'
          $OsmFile = 'berlin-latest.osm.pbf'
          $JavaOpts = '-Xmx1g -Xms256m -XX:+UseG1GC' }
    '5' { $OsmUrl  = Read-Input 'OSM-Download-URL'
          $OsmFile = [IO.Path]::GetFileName($OsmUrl)
          $JavaOpts = '-Xmx4g -Xms1g -XX:+UseG1GC' }
    default { Write-Host "FEHLER: Ungueltige Auswahl '$OsmChoice'." -ForegroundColor Red; exit 1 }
}

$LicenseKey   = Read-Host 'Lizenzschluessel [Enter = Demo-Modus]'
# Read the token without echoing it to the screen / PSReadline history. It still
# has to be written to .env in clear (the updater needs it) — use a fine-grained
# PAT with minimal scope (read:packages).
$GithubTokenSecure = Read-Host 'GitHub Token fuer Auto-Updater [Enter = ueberspringen]' -AsSecureString
$GithubToken = [System.Net.NetworkCredential]::new('', $GithubTokenSecure).Password

# JWT_SECRET: bestehenden beibehalten oder neu generieren
$existingJwt = if (Test-Path $EnvFile) { Get-EnvValue 'JWT_SECRET' $EnvFile } else { '' }
if ($existingJwt) {
    $JwtSecret = $existingJwt
} else {
    $Rng   = [Security.Cryptography.RandomNumberGenerator]::Create()
    $Bytes = New-Object byte[] 32
    $Rng.GetBytes($Bytes)
    $JwtSecret = ($Bytes | ForEach-Object { $_.ToString('x2') }) -join ''
}

# Installationsverzeichnis anlegen
if ((Test-Path $InstallDir) -and (Test-Path $EnvFile)) {
    # Konfiguration existiert — Update-Modus wurde oben bereits angeboten.
    # Hier nur noch sicherstellen dass das Verzeichnis schreibbar ist.
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir 'caddy') | Out-Null

Write-Host ''
Write-Host '-> Stack-Konfiguration herunterladen...'
try {
    Invoke-WebRequest -Uri $StackUrl -OutFile (Join-Path $InstallDir 'docker-compose.yml') -UseBasicParsing
} catch {
    Write-Host 'FEHLER: Stack-Datei konnte nicht heruntergeladen werden.' -ForegroundColor Red
    Remove-Item -Path (Join-Path $InstallDir 'docker-compose.yml') -ErrorAction SilentlyContinue
    exit 1
}
try {
    Invoke-WebRequest -Uri $CaddyEntrypointUrl -OutFile (Join-Path $InstallDir 'caddy\entrypoint.sh') -UseBasicParsing
} catch {
    Write-Host 'FEHLER: Caddy-Entrypoint konnte nicht heruntergeladen werden.' -ForegroundColor Red; exit 1
}

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
JAVA_OPTS="$JavaOpts"
BACKEND_IMAGE=ghcr.io/retttechsolutions/convoyplan/backend:latest
FRONTEND_IMAGE=ghcr.io/retttechsolutions/convoyplan/frontend:latest
GRAPHHOPPER_IMAGE=ghcr.io/retttechsolutions/convoyplan/graphhopper:latest
UPDATER_IMAGE=ghcr.io/retttechsolutions/convoyplan/updater:latest
GITHUB_REPO=RettTechSolutions/ConvoyPlan
STACK_FILE_PATH=$InstallDir\docker-compose.yml
CADDY_ENTRYPOINT_PATH=$InstallDir\caddy\entrypoint.sh
COMPOSE_PROJECT_NAME=convoyplan
"@
if ($LicenseKey)  { $EnvContent += "`nLICENSE_KEY=$LicenseKey" }
if ($GithubToken) { $EnvContent += "`nGITHUB_TOKEN=$GithubToken" }

# Write UTF-8 WITHOUT BOM — Windows PowerShell 5.1's `Set-Content -Encoding UTF8`
# prepends a BOM, which makes Docker Compose read the first line as
# "﻿POSTGRES_USER" and silently fall back to defaults.
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText((Join-Path $InstallDir '.env'), $EnvContent, $Utf8NoBom)

# Stack starten
Write-Host ''
Write-Host '-> Images herunterladen (kann einige Minuten dauern)...'
docker compose --project-directory $InstallDir pull

Write-Host ''
Write-Host '-> ConvoyPlan starten...'
docker compose --project-directory $InstallDir up -d

Write-Host ''
Write-Host '╔══════════════════════════════════════════════════════════╗' -ForegroundColor Green
Write-Host '║  ConvoyPlan laeuft!                                      ║' -ForegroundColor Green
Write-Host ("║  Setup-Wizard: https://$Domain/setup").PadRight(61) + "║" -ForegroundColor Green
Write-Host '╚══════════════════════════════════════════════════════════╝' -ForegroundColor Green
Write-Host ''
