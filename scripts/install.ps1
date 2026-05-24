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
    if ($overwrite -ine 'j') { Write-Host 'Abgebrochen.'; exit 0 }
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# Stack-Datei herunterladen
Write-Host ''
Write-Host '-> Stack-Konfiguration herunterladen...'
try {
    Invoke-WebRequest -Uri $StackUrl -OutFile (Join-Path $InstallDir 'docker-compose.yml') -UseBasicParsing
} catch {
    Write-Host 'FEHLER: Stack-Datei konnte nicht heruntergeladen werden.' -ForegroundColor Red
    Remove-Item -Path (Join-Path $InstallDir 'docker-compose.yml') -ErrorAction SilentlyContinue
    exit 1
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
JAVA_OPTS="-Xmx2g -Xms512m -XX:+UseG1GC"
BACKEND_IMAGE=ghcr.io/retttechsolutions/convoyplan-backend:latest
FRONTEND_IMAGE=ghcr.io/retttechsolutions/convoyplan-frontend:latest
GRAPHHOPPER_IMAGE=ghcr.io/retttechsolutions/convoyplan-graphhopper:latest
GITHUB_REPO=RettTechSolutions/ConvoyPlan
"@
if ($LicenseKey)  { $EnvContent += "`nLICENSE_KEY=$LicenseKey" }
if ($GithubToken) { $EnvContent += "`nGITHUB_TOKEN=$GithubToken" }

Set-Content -Path (Join-Path $InstallDir '.env') -Value $EnvContent -Encoding UTF8

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
