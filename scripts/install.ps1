#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRaw           = 'https://raw.githubusercontent.com/RettTechSolutions/ConvoyPlan/main'
$StackUrl          = "$RepoRaw/docker-compose.yml"
$CaddyEntrypointUrl = "$RepoRaw/caddy/entrypoint.sh"

Write-Host ''
Write-Host @'
   ____                            ____  _
  / ___|___  _ ____   _____  _   _|  _ \| | __ _ _ __
 | |   / _ \| '_ \ \ / / _ \| | | | |_) | |/ _` | '_ \
 | |__| (_) | | | \ V / (_) | |_| |  __/| | (_| | | | |
  \____\___/|_| |_|\_/ \___/ \__, |_|   |_|\__,_|_| |_|
                             |___/            Installer
'@ -ForegroundColor Cyan
Write-Host @'

  _________ ___    _________ ___       __*__
 |_________|__|\  |_________|__|\   __/__|__\_
==(o)(o)====(o)====(o)(o)====(o)===='-(o)--(o)'=======

'@

# ── Konvoi-Ladebalken ────────────────────────────────────────────────────────
# Lange Schritte laufen im Hintergrund, waehrend ein Konvoi ueber die Strasse
# faehrt. Wo der Fortschritt messbar ist (Images ziehen), faehrt er genau so
# weit; sonst rollt er langsam aus und erreicht das Ziel erst am Ende. Die
# Ausgabe des Befehls landet in Logdateien und wird nur bei einem Fehler
# gezeigt. Ohne Konsole (umgeleitet, ISE, CONVOYPLAN_PLAIN=1) laeuft alles wie
# frueher mit voller Ausgabe. Gleiche Bilder wie in install.sh.
$KonvoiLkw  = @(' _________ ___ ', '|_________|__|\', ' (o)(o)    (o) ')
$KonvoiKdow = @('    __*__   ', ' __/__|__\_ ', " '-(o)--(o)'")

function Test-KonvoiMoeglich {
    if ($env:CONVOYPLAN_PLAIN) { return $false }
    if ($Host.Name -ne 'ConsoleHost') { return $false }
    try {
        if ([Console]::IsOutputRedirected) { return $false }
        return ([Console]::WindowWidth -ge 60)
    } catch { return $false }
}

function Write-KonvoiBild {
    param([int]$Start, [int]$Promille, [int]$Bild, [string]$Status, [ConsoleColor]$StatusFarbe = 'Gray')
    $breite = [Math]::Min([Console]::WindowWidth - 1, 100)
    $konvoiBreite = $KonvoiLkw[0].Length * 2 + $KonvoiKdow[0].Length + 4
    $x = [int][Math]::Floor(($breite - $konvoiBreite) * $Promille / 1000)
    $einzug = ' ' * $x
    [Console]::SetCursorPosition(0, $Start)
    for ($i = 0; $i -lt 3; $i++) {
        $zeile = $einzug + $KonvoiLkw[$i] + '  ' + $KonvoiLkw[$i] + '  ' + $KonvoiKdow[$i]
        if ($i -eq 0) {
            # Blaulicht blinkt
            $pos = $zeile.IndexOf('*')
            Write-Host $zeile.Substring(0, $pos) -NoNewline
            $farbe = if ($Bild % 2) { 'Blue' } else { 'Cyan' }
            Write-Host '*' -NoNewline -ForegroundColor $farbe
            Write-Host $zeile.Substring($pos + 1).PadRight($breite - $pos - 1)
        } else {
            Write-Host $zeile.PadRight($breite)
        }
    }
    $strasse = -join (0..($breite - 1) | ForEach-Object { if ((($_ + $Bild) % 4) -lt 2) { '=' } else { '-' } })
    Write-Host $strasse
    Write-Host ('  ' + $Status).PadRight($breite) -ForegroundColor $StatusFarbe
}

function Read-KonvoiLog {
    param([string[]]$Pfade)
    $text = ''
    foreach ($p in $Pfade) {
        try {
            $fs = [IO.File]::Open($p, 'Open', 'Read', 'ReadWrite')
            try { $text += (New-Object IO.StreamReader($fs)).ReadToEnd() } finally { $fs.Dispose() }
        } catch { }
    }
    return $text
}

# Invoke-Konvoi 'Beschriftung' @('compose', ..., 'pull') [-Gesamt n]
# Gibt den Exit-Code von docker zurueck. Mit -Gesamt zaehlt der Balken fertige Dienste.
function Invoke-Konvoi {
    param([string]$Beschriftung, [string[]]$DockerArgs, [int]$Gesamt = 0)
    $start = -1
    if (Test-KonvoiMoeglich) {
        # Platz fuer das Bild schaffen; die Konsole muss die Cursorposition
        # kennen, sonst lieber ohne Animation als mit kaputtem Bild.
        Write-Host ''
        1..5 | ForEach-Object { Write-Host '' }
        try { $start = [Console]::CursorTop - 5 } catch { $start = -1 }
    }
    if ($start -lt 0) {
        Write-Host "-> $Beschriftung..."
        & docker @DockerArgs | Out-Host
        return $LASTEXITCODE
    }

    # Start-Process setzt die Argumente nur mit Leerzeichen zusammen — Pfade
    # wie C:\Users\Max Muster\convoyplan muessen selbst in Anfuehrungszeichen.
    $Argumente = ($DockerArgs | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } }) -join ' '

    $out = [IO.Path]::GetTempFileName()
    $err = [IO.Path]::GetTempFileName()
    $p = Start-Process docker -ArgumentList $Argumente -NoNewWindow -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $p.Handle   # sonst bleibt ExitCode unter Windows PowerShell leer

    $bild = 0; $promille = 0
    try {
        [Console]::CursorVisible = $false
        while (-not $p.HasExited) {
            $anzeige = ''
            if ($Gesamt -gt 0) {
                $fertig = ([regex]::Matches((Read-KonvoiLog @($out, $err)), ' (Pulled|Skipped)')).Count
                $fertig = [Math]::Min($fertig, $Gesamt)
                $ziel = [int]($fertig * 1000 / $Gesamt)
                # Nicht erkannt (anderes Ausgabeformat)? Langsam weiterrollen.
                $ziel = [Math]::Max($ziel, [int](950 * $bild / ($bild + 2000)))
                $anzeige = "  [$fertig/$Gesamt]"
            } else {
                $ziel = [int](950 * $bild / ($bild + 80))
            }
            $ziel = [Math]::Min($ziel, 950)
            if ($promille -lt $ziel) { $promille += [int][Math]::Ceiling(($ziel - $promille) / 10) }
            Write-KonvoiBild -Start $start -Promille $promille -Bild $bild -Status ($Beschriftung + $anzeige)
            $bild++
            Start-Sleep -Milliseconds 120
        }
        $p.WaitForExit()
        $rc = $p.ExitCode
        if ($rc -eq 0) {
            Write-KonvoiBild -Start $start -Promille 1000 -Bild 0 -Status "✓ $Beschriftung" -StatusFarbe Green
        } else {
            Write-KonvoiBild -Start $start -Promille $promille -Bild 0 -Status "✗ $Beschriftung fehlgeschlagen (Exit $rc):" -StatusFarbe Red
            # Fortschrittszeilen der Schichten ausblenden, sonst geht der Fehler
            # zwischen lauter "Downloading 1.049MB" unter
            (Read-KonvoiLog @($out, $err)) -split "`r?`n" |
                Where-Object { $_ -and $_ -notmatch ' (Downloading|Extracting|Waiting|Verifying Checksum|Download complete|Pull complete|Pulling fs layer|Already exists)' } |
                Select-Object -Last 20 | ForEach-Object { Write-Host "    $_" }
        }
        return $rc
    } finally {
        if (-not $p.HasExited) { $p.Kill() }
        [Console]::CursorVisible = $true
        Remove-Item $out, $err -ErrorAction SilentlyContinue
    }
}

# Bis zu drei Versuche: ein Timeout zur Registry (Docker Hub, ghcr.io) ist
# meist voruebergehend, und bereits geladene Schichten bleiben liegen.
function Invoke-ImagesZiehen {
    param([string]$Verzeichnis)
    $gesamt = @(docker compose --project-directory $Verzeichnis config --services 2>$null).Count
    $beschriftung = 'Images laden (kann einige Minuten dauern)'
    for ($versuch = 1; $versuch -le 3; $versuch++) {
        $rc = Invoke-Konvoi $beschriftung @('compose', '--project-directory', $Verzeichnis, 'pull') -Gesamt $gesamt
        if ($rc -eq 0) { return }
        if ($versuch -lt 3) {
            Write-Host "  Neuer Versuch in $($versuch * 10) s; bereits geladene Schichten bleiben erhalten."
            Start-Sleep -Seconds ($versuch * 10)
            $beschriftung = "Images laden (Versuch $($versuch + 1)/3)"
        }
    }
    Write-Host ''
    Write-Host 'FEHLER: Die Images liessen sich nicht laden. Meist ist die Verbindung zur' -ForegroundColor Red
    Write-Host '        Registry gestoert (Docker Hub, ghcr.io): Netzwerk, Proxy oder DNS pruefen.' -ForegroundColor Red
    Write-Host '        Danach den Installer erneut starten und [J] Nur aktualisieren waehlen.' -ForegroundColor Red
    Write-Host '        Die Einstellungen sind bereits gespeichert.' -ForegroundColor Red
    exit 1
}

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
        # NetworkCredential statt PtrToStringAuto(SecureStringToBSTR(...)): Das
        # liest den UTF-16-BSTR ausserhalb von Windows als UTF-8 und kuerzt am
        # ersten Nullbyte — aus "geheim" wurde "g". Lecken tut der BSTR auch nicht.
        $p1 = [System.Net.NetworkCredential]::new('', $s1).Password
        $p2 = [System.Net.NetworkCredential]::new('', $s2).Password
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
            Add-EnvKeyIfMissing 'REGION_MERGE_IMAGE'    'ghcr.io/retttechsolutions/convoyplan/osmium:latest'      $EnvFile
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

            Invoke-ImagesZiehen $InstallDir
            $null = Invoke-Konvoi 'ConvoyPlan neu starten' @('compose', '--project-directory', $InstallDir, 'up', '-d')

            Write-Host ''
            Write-Host '╔══════════════════════════════════════════════════════════╗' -ForegroundColor Green
            Write-Host '║  ConvoyPlan wurde aktualisiert!                          ║' -ForegroundColor Green
            Write-Host (("║  URL: https://$existingDomain/").PadRight(59) + "║")    -ForegroundColor Green
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
        $typed = [System.Net.NetworkCredential]::new('', $s1).Password
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
# Bei einer Neukonfiguration bleibt die bisherige Region mit Enter erhalten —
# wie in install.sh. Frueher fiel Enter hier auf DACH zurueck.
$PrevOsmUrl   = if (Test-Path $EnvFile) { Get-EnvValue 'OSM_DOWNLOAD_URL' $EnvFile } else { '' }
$PrevOsmFile  = if (Test-Path $EnvFile) { Get-EnvValue 'OSM_FILENAME' $EnvFile } else { '' }
# JAVA_OPTS steht in Anfuehrungszeichen in der .env — abziehen, sonst kommt bei
# jeder Neukonfiguration eine Schicht dazu (""-Xmx8g ..."" liest Compose als leer).
$PrevJavaOpts = if (Test-Path $EnvFile) { (Get-EnvValue 'JAVA_OPTS' $EnvFile).Trim('"') } else { '' }
if ($PrevOsmFile) {
    $OsmChoice = Read-Host "Auswahl [Enter = beibehalten: $PrevOsmFile]"
} else {
    $OsmChoice = Read-Host 'Auswahl [1]'
    if (-not $OsmChoice) { $OsmChoice = '1' }
}

# JAVA_OPTS scale with the region's PBF size — must match install.sh, otherwise
# the DACH default OOMs on a 2 GB heap during the graph import.
switch ($OsmChoice) {
    ''  { $OsmUrl  = $PrevOsmUrl
          $OsmFile = $PrevOsmFile
          $JavaOpts = if ($PrevJavaOpts) { $PrevJavaOpts } else { '-Xmx4g -Xms1g -XX:+UseG1GC' } }
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

# Lizenzschluessel: bei einer Neukonfiguration bleibt ein vorhandener
# Wert mit Enter erhalten. Frueher schrieb das Skript die .env ohne ihn neu, und
# der Schluessel war weg.
$PrevLicense = if (Test-Path $EnvFile) { Get-EnvValue 'LICENSE_KEY' $EnvFile } else { '' }
$PrevToken   = if (Test-Path $EnvFile) { Get-EnvValue 'GITHUB_TOKEN' $EnvFile } else { '' }

if ($PrevLicense) {
    $LicenseKey = Read-Host 'Lizenzschluessel [Enter = bestehenden beibehalten]'
    if (-not $LicenseKey) { $LicenseKey = $PrevLicense }
} else {
    $LicenseKey = Read-Host 'Lizenzschluessel [Enter = Demo-Modus]'
}
# Kein GitHub-Token: Das Repository ist oeffentlich, Updater und Backend lesen
# die GitHub-API auch ohne. Ein Token hebt nur das Rate-Limit (60 -> 5000
# Anfragen/Stunde je IP) und laesst sich bei Bedarf im Admin-Panel hinterlegen.
# Ein vorhandener Eintrag aus einer frueheren Installation bleibt erhalten.
$GithubToken = $PrevToken

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
REGION_MERGE_IMAGE=ghcr.io/retttechsolutions/convoyplan/osmium:latest
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
# Mit Zeilenende am Schluss — sonst klebt ein spaeteres `echo ... >> .env`
# an der letzten Zeile fest.
[System.IO.File]::WriteAllText((Join-Path $InstallDir '.env'), $EnvContent + "`n", $Utf8NoBom)

# Stack starten
Invoke-ImagesZiehen $InstallDir
$null = Invoke-Konvoi 'ConvoyPlan starten' @('compose', '--project-directory', $InstallDir, 'up', '-d')

Write-Host ''
Write-Host '╔══════════════════════════════════════════════════════════╗' -ForegroundColor Green
Write-Host '║  ConvoyPlan laeuft!                                      ║' -ForegroundColor Green
Write-Host (("║  Setup-Wizard: https://$Domain/setup").PadRight(59) + "║") -ForegroundColor Green
Write-Host '╚══════════════════════════════════════════════════════════╝' -ForegroundColor Green
Write-Host ''
