#!/usr/bin/env bash
set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/RettTechSolutions/ConvoyPlan/main"
STACK_URL="$REPO_RAW/docker-compose.yml"
CADDY_ENTRYPOINT_URL="$REPO_RAW/caddy/entrypoint.sh"
WATCHDOG_URL="$REPO_RAW/scripts/updater-watchdog.sh"

cat <<'BANNER'

   ____                            ____  _
  / ___|___  _ ____   _____  _   _|  _ \| | __ _ _ __
 | |   / _ \| '_ \ \ / / _ \| | | | |_) | |/ _` | '_ \
 | |__| (_) | | | \ V / (_) | |_| |  __/| | (_| | | | |
  \____\___/|_| |_|\_/ \___/ \__, |_|   |_|\__,_|_| |_|
                             |___/            Installer

  _________ ___    _________ ___       __*__
 |_________|__|\  |_________|__|\   __/__|__\_
==(o)(o)====(o)====(o)(o)====(o)===='-(o)--(o)'=======

BANNER

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

# sudo-Verfügbarkeit prüfen (wird für root-eigene Docker-Artefakte benötigt)
if [[ "$EUID" -ne 0 ]] && ! sudo -n true 2>/dev/null; then
  echo ""
  echo "Dieser Installer benötigt sudo-Rechte, um von Docker als root angelegte"
  echo "Verzeichnisse bereinigen zu können. Bitte sudo-Passwort einmalig eingeben:"
  sudo true || { echo "FEHLER: sudo nicht verfügbar. Installation als root starten: sudo bash"; exit 1; }
fi
echo "✓ sudo verfügbar"
echo ""

# Hilfsfunktionen
prompt() {
  local msg="$1" default="$2" varname="$3"
  local val
  if [[ -n "$default" ]]; then
    read -rp "$msg [$default]: " val </dev/tty
    printf -v "$varname" '%s' "${val:-$default}"
  else
    while true; do
      read -rp "$msg: " val </dev/tty
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
    read -rsp "$msg: " val1 </dev/tty; echo
    read -rsp "Passwort bestätigen: " val2 </dev/tty; echo
    if [[ -n "$val1" && "$val1" == "$val2" ]]; then
      printf -v "$varname" '%s' "$val1"
      break
    fi
    echo "  Passwörter stimmen nicht überein oder leer. Erneut versuchen."
  done
}

# ── Konvoi-Ladebalken ────────────────────────────────────────────────────────
# Lange Schritte laufen im Hintergrund, während ein Konvoi über die Straße
# fährt. Wo der Fortschritt messbar ist (Images ziehen), fährt er genau so weit;
# sonst rollt er langsam aus und erreicht das Ziel erst, wenn der Schritt fertig
# ist. Die Ausgabe des Befehls landet in einer Logdatei und wird nur bei einem
# Fehler gezeigt. Ohne Terminal (Pipe, CI, CONVOYPLAN_PLAIN=1) läuft alles wie
# früher mit voller Ausgabe.
_KONVOI_LKW=(
  ' _________ ___ '
  '|_________|__|\'
  ' (o)(o)    (o) '
)
_KONVOI_KDOW=(
  '    __*__   '
  ' __/__|__\_ '
  " '-(o)--(o)'"
)
_KONVOI_HOEHE=5   # drei Zeilen Fahrzeuge, Straße, Statuszeile

_konvoi_moeglich() {
  [[ -t 1 && "${TERM:-dumb}" != "dumb" && -z "${CONVOYPLAN_PLAIN:-}" ]] || return 1
  local cols; cols=$(tput cols 2>/dev/null || echo 0)
  (( cols >= 60 ))
}

# Zeichnet ein Bild. $1 = Fortschritt in Promille, $2 = Bildnummer, $3 = Statuszeile
_konvoi_bild() {
  local promille="$1" bild="$2" status="$3"
  local cols breite strecke x i zeile licht strasse
  cols=$(tput cols 2>/dev/null || echo 80)
  breite=$(( cols > 101 ? 100 : cols - 1 ))
  # Konvoi = LKW, LKW, KdoW vorneweg (fährt nach rechts)
  local konvoi_breite=$(( ${#_KONVOI_LKW[0]} * 2 + ${#_KONVOI_KDOW[0]} + 4 ))
  strecke=$(( breite - konvoi_breite ))
  x=$(( strecke * promille / 1000 ))

  # Blaulicht blinkt; mit Farbe blau, ohne Farbe an/aus
  if [[ -z "${NO_COLOR:-}" ]]; then
    (( bild % 2 )) && licht=$'\e[1;34m*\e[0m' || licht=$'\e[1;36m*\e[0m'
  else
    (( bild % 2 )) && licht='*' || licht=' '
  fi

  for i in 0 1 2; do
    zeile="$(printf '%*s' "$x" '')${_KONVOI_LKW[$i]}  ${_KONVOI_LKW[$i]}  ${_KONVOI_KDOW[$i]}"
    (( i == 0 )) && zeile="${zeile/\*/$licht}"
    printf '\e[2K%s\n' "$zeile"
  done

  # Fahrbahnmarkierung zieht unter dem Konvoi nach links weg
  strasse=""
  for (( i = 0; i < breite; i++ )); do
    (( (i + bild) % 4 < 2 )) && strasse+="=" || strasse+="-"
  done
  printf '\e[2K%s\n' "$strasse"
  printf '\e[2K  %s\n' "$status"
}

# Fortschritt beim Ziehen: fertige Dienste / alle Dienste
_konvoi_fortschritt_pull() {
  local log="$1" fertig
  fertig=$(grep -cE ' (Pulled|Skipped)' "$log" 2>/dev/null || true)
  fertig=${fertig:-0}
  (( _KONVOI_GESAMT > 0 )) || { echo -1; return; }
  (( fertig > _KONVOI_GESAMT )) && fertig=$_KONVOI_GESAMT
  echo $(( fertig * 1000 / _KONVOI_GESAMT )) "${fertig}/${_KONVOI_GESAMT}"
}

# _konvoi "Beschriftung" fortschrittsfunktion|- befehl...
_konvoi() {
  local beschriftung="$1" fortschritt_fn="$2"; shift 2
  if ! _konvoi_moeglich; then
    echo "→ ${beschriftung}..."
    "$@"
    return
  fi

  local log; log=$(mktemp)
  "$@" >"$log" 2>&1 &
  local pid=$! bild=0 promille=0 ziel anzeige rc=0 rest

  tput civis 2>/dev/null || true
  trap 'kill "$pid" 2>/dev/null; tput cnorm 2>/dev/null; rm -f "$log"; echo; exit 130' INT TERM
  echo ""
  for (( rest = 0; rest < _KONVOI_HOEHE; rest++ )); do echo; done

  while kill -0 "$pid" 2>/dev/null; do
    anzeige=""
    ziel=-1
    if [[ "$fortschritt_fn" != "-" ]]; then
      read -r ziel anzeige < <("$fortschritt_fn" "$log")
    fi
    if (( ziel < 0 )); then
      # Nicht messbar: nähert sich 95 %, ohne es zu erreichen
      ziel=$(( 950 * bild / (bild + 80) ))
    else
      # Messbar, aber vielleicht nicht erkannt (anderes Ausgabeformat von
      # Compose): langsam weiterrollen statt stehenzubleiben
      local kriechen=$(( 950 * bild / (bild + 2000) ))
      (( kriechen > ziel )) && ziel=$kriechen
    fi
    (( ziel > 950 )) && ziel=950
    # Sanft hinfahren statt springen
    (( promille < ziel )) && promille=$(( promille + (ziel - promille + 9) / 10 ))
    printf '\e[%dA' "$_KONVOI_HOEHE"
    _konvoi_bild "$promille" "$bild" "${beschriftung}${anzeige:+  [$anzeige]}"
    bild=$(( bild + 1 ))
    sleep 0.12
  done
  wait "$pid" || rc=$?

  printf '\e[%dA' "$_KONVOI_HOEHE"
  if (( rc == 0 )); then
    _konvoi_bild 1000 0 "✓ ${beschriftung}"
  else
    _konvoi_bild "$promille" 0 "✗ ${beschriftung} fehlgeschlagen (Exit ${rc}):"
    # Fortschrittszeilen der Schichten ausblenden, sonst bestehen die letzten
    # 20 Zeilen nur aus "Downloading 1.049MB" und der Fehler geht unter
    grep -vE ' (Downloading|Extracting|Waiting|Verifying Checksum|Download complete|Pull complete|Pulling fs layer|Already exists)' "$log" \
      | tail -n 20 | sed 's/^/    /' || true
  fi
  tput cnorm 2>/dev/null || true
  trap - INT TERM
  rm -f "$log"
  return "$rc"
}

_KONVOI_GESAMT=0
# Bis zu drei Versuche: ein Timeout zur Registry (Docker Hub, ghcr.io) ist
# meist vorübergehend, und bereits geladene Schichten bleiben liegen.
_images_ziehen() {
  # $(( )) statt nackt: wc -l rückt die Zahl unter macOS mit Leerzeichen ein
  _KONVOI_GESAMT=$(( $(docker compose --project-directory "$1" config --services 2>/dev/null | wc -l) ))
  local versuch rc=0 beschriftung="Images laden (kann einige Minuten dauern)"
  for versuch in 1 2 3; do
    rc=0
    _konvoi "$beschriftung" _konvoi_fortschritt_pull \
      docker compose --project-directory "$1" pull || rc=$?
    (( rc == 0 )) && return 0
    if (( versuch < 3 )); then
      echo "  Neuer Versuch in $(( versuch * 10 )) s; bereits geladene Schichten bleiben erhalten."
      sleep $(( versuch * 10 ))
      beschriftung="Images laden (Versuch $(( versuch + 1 ))/3)"
    fi
  done
  echo ""
  echo "FEHLER: Die Images ließen sich nicht laden. Meist ist die Verbindung zur"
  echo "        Registry gestört (Docker Hub, ghcr.io): Netzwerk, Proxy oder DNS prüfen."
  echo "        Danach den Installer erneut starten und [J] Nur aktualisieren wählen."
  echo "        Die Einstellungen sind bereits gespeichert."
  return "$rc"
}

# ── Cleanup orphan hex-prefixed updater containers ───────────────────────────
# Releases from before this fix could leave a `<hex>_convoyplan-updater-1`
# container in Created/Exited state when the updater's self-restart raced.
# Remove them so `docker compose up -d` starts the stack cleanly.
_cleanup_orphan_updaters() {
  local project="${1:-convoyplan}"
  local orphans
  orphans=$(docker ps -a \
      --filter "name=^[0-9a-f]{12}_${project}-updater-1$" \
      --format "{{.Names}}" 2>/dev/null || true)
  for c in $orphans; do
    echo "  → räume Orphan-Updater-Container ${c} auf"
    docker rm -f "${c}" >/dev/null 2>&1 || true
  done
}

# ── Install systemd watchdog timer ───────────────────────────────────────────
# Belt-and-suspenders: even if the updater's in-container self-restart fails,
# the watchdog runs on the host every ~2 min and recovers a stuck stack.
# Silently skipped on non-systemd systems.
_install_watchdog() {
  local install_dir="$1"

  if ! command -v systemctl &>/dev/null || ! [ -d /run/systemd/system ]; then
    echo "  → systemd nicht erkannt — Watchdog wird übersprungen"
    return 0
  fi

  echo "→ Self-healing-Watchdog (systemd-Timer) installieren..."
  curl -sSfL "$WATCHDOG_URL" -o "$install_dir/updater-watchdog.sh" \
    || { echo "  WARNUNG: Watchdog-Skript konnte nicht heruntergeladen werden — Watchdog wird übersprungen"; return 0; }
  chmod +x "$install_dir/updater-watchdog.sh"

  sudo tee /etc/systemd/system/convoyplan-updater-watchdog.service >/dev/null <<UNIT
[Unit]
Description=ConvoyPlan updater self-healing watchdog
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart="${install_dir}/updater-watchdog.sh" "${install_dir}"
UNIT

  sudo tee /etc/systemd/system/convoyplan-updater-watchdog.timer >/dev/null <<UNIT
[Unit]
Description=Run ConvoyPlan updater watchdog every 2 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=2min
Unit=convoyplan-updater-watchdog.service
Persistent=true

[Install]
WantedBy=timers.target
UNIT

  sudo systemctl daemon-reload
  sudo systemctl enable --now convoyplan-updater-watchdog.timer >/dev/null 2>&1
  echo "  ✓ Watchdog aktiv (alle 2 Min.)"
}

# Eingaben
prompt "Installationsverzeichnis" "$HOME/convoyplan" INSTALL_DIR

# Validate before any `sudo chown -R "$INSTALL_DIR"` runs: require an absolute
# path and refuse the filesystem root / critical system directories so a typo or
# empty value can never recursively re-own the host.
case "$INSTALL_DIR" in
  /*) : ;;
  *) echo "FEHLER: Installationsverzeichnis muss ein absoluter Pfad sein." >&2; exit 1 ;;
esac
case "$INSTALL_DIR" in
  "/" | "/usr" | "/usr/"* | "/etc" | "/etc/"* | "/bin" | "/sbin" | "/lib" | "/lib/"* \
  | "/var" | "/var/"* | "/boot" | "/dev" | "/proc" | "/sys" | "/home" | "/root")
    echo "FEHLER: Ungültiges Installationsverzeichnis '$INSTALL_DIR' — bitte einen dedizierten Pfad wählen (z. B. \$HOME/convoyplan)." >&2
    exit 1 ;;
esac

# ── Bestehende Installation erkennen ─────────────────────────────────────────
PREV_DOMAIN="" PREV_EMAIL="" PREV_DB_PASS="" PREV_JWT=""
PREV_OSM_URL="" PREV_OSM_FILE="" PREV_JAVA_OPTS=""
PREV_LICENSE="" PREV_GH_TOKEN="" PREV_INSTANCE_MODE=""

_ev() { grep -m1 "^${1}=" "$INSTALL_DIR/.env" 2>/dev/null | cut -d= -f2- || true; }

if [[ -f "$INSTALL_DIR/.env" ]] && \
   [[ -n "$(_ev POSTGRES_PASSWORD)" ]] && \
   [[ -n "$(_ev DOMAIN)" ]]; then

  echo ""
  echo "Bestehende ConvoyPlan-Installation in '$INSTALL_DIR' gefunden."
  echo "  [J] Nur aktualisieren — Einstellungen beibehalten  (empfohlen)"
  echo "  [n] Neu konfigurieren — Werte als Vorauswahl laden"
  read -rp "Auswahl [J/n]: " _upd </dev/tty || true

  # Nicht ${_upd,,}: macOS bringt Bash 3.2 mit, die kennt das erst ab Bash 4.
  if [[ "$_upd" != [nN] ]]; then
    # ── UPDATE-MODUS: fehlende Keys ergänzen, Compose-Datei erneuern, neu starten ──
    _patch_env() {
      local key="$1" val="$2"
      if ! grep -q "^${key}=" "$INSTALL_DIR/.env" 2>/dev/null; then
        echo "${key}=${val}" >> "$INSTALL_DIR/.env"
        echo "  + ${key} ergänzt"
      fi
    }

    echo ""
    echo "→ Fehlende Konfigurationseinträge ergänzen..."
    _patch_env "STACK_FILE_PATH"         "${INSTALL_DIR}/docker-compose.yml"
    _patch_env "CADDY_ENTRYPOINT_PATH"   "${INSTALL_DIR}/caddy/entrypoint.sh"
    _patch_env "COMPOSE_PROJECT_NAME"    "convoyplan"
    _patch_env "UPDATER_IMAGE"           "ghcr.io/retttechsolutions/convoyplan/updater:latest"
    _patch_env "BACKEND_IMAGE"           "ghcr.io/retttechsolutions/convoyplan/backend:latest"
    _patch_env "FRONTEND_IMAGE"          "ghcr.io/retttechsolutions/convoyplan/frontend:latest"
    _patch_env "GRAPHHOPPER_IMAGE"       "ghcr.io/retttechsolutions/convoyplan/graphhopper:latest"
    _patch_env "REGION_MERGE_IMAGE"      "ghcr.io/retttechsolutions/convoyplan/osmium:latest"
    _patch_env "GITHUB_REPO"             "RettTechSolutions/ConvoyPlan"
    _patch_env "INSTANCE_MODE"           "selfhost"

    sudo chown -R "$(id -u):$(id -g)" "$INSTALL_DIR"
    rm -f "$INSTALL_DIR/docker-compose.yml"
    mkdir -p "$INSTALL_DIR/caddy"

    echo "→ Neueste Stack-Konfiguration herunterladen..."
    curl -sSfL "$STACK_URL" -o "$INSTALL_DIR/docker-compose.yml" \
      || { echo "FEHLER: Stack-Datei konnte nicht heruntergeladen werden."; exit 1; }
    curl -sSfL "$CADDY_ENTRYPOINT_URL" -o "$INSTALL_DIR/caddy/entrypoint.sh" \
      || { echo "FEHLER: Caddy-Entrypoint konnte nicht heruntergeladen werden."; exit 1; }
    chmod +x "$INSTALL_DIR/caddy/entrypoint.sh"

    _images_ziehen "$INSTALL_DIR"

    echo "→ Verwaiste Updater-Container aufräumen..."
    _cleanup_orphan_updaters "$(_ev COMPOSE_PROJECT_NAME)"

    _konvoi "ConvoyPlan neu starten" - \
      docker compose --project-directory "$INSTALL_DIR" up -d || true

    _install_watchdog "$INSTALL_DIR"

    CURRENT_DOMAIN="$(_ev DOMAIN)"
    echo ""
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║  ConvoyPlan wurde aktualisiert!                          ║"
    printf "║  URL: https://%-43s║\n" "${CURRENT_DOMAIN}/"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo ""
    exit 0
  fi

  # ── NEU-KONFIGURIEREN mit bestehenden Werten als Vorauswahl ──────────────
  echo ""
  PREV_DOMAIN=$(_ev DOMAIN)
  PREV_EMAIL=$(_ev ACME_EMAIL)
  PREV_DB_PASS=$(_ev POSTGRES_PASSWORD)
  PREV_JWT=$(_ev JWT_SECRET)
  PREV_INSTANCE_MODE=$(_ev INSTANCE_MODE)
  PREV_OSM_URL=$(_ev OSM_DOWNLOAD_URL)
  PREV_OSM_FILE=$(_ev OSM_FILENAME)
  # Steht in Anführungszeichen in der .env — abziehen, sonst kommt bei jeder
  # Neukonfiguration eine Schicht dazu (""-Xmx8g …"" liest Compose als leer).
  PREV_JAVA_OPTS=$(_ev JAVA_OPTS | sed -E 's/^"+//; s/"+$//')
  PREV_LICENSE=$(_ev LICENSE_KEY)
  PREV_GH_TOKEN=$(_ev GITHUB_TOKEN)
  echo "✓ Bestehende Werte geladen."
  echo ""

elif [[ -f "$INSTALL_DIR/.env" ]]; then
  # Unvollständige .env — Werte als Vorauswahl laden, vollständige Konfiguration abfragen
  PREV_DOMAIN=$(_ev DOMAIN)
  PREV_EMAIL=$(_ev ACME_EMAIL)
  PREV_DB_PASS=$(_ev POSTGRES_PASSWORD)
  PREV_JWT=$(_ev JWT_SECRET)
  PREV_INSTANCE_MODE=$(_ev INSTANCE_MODE)
  PREV_OSM_URL=$(_ev OSM_DOWNLOAD_URL)
  PREV_OSM_FILE=$(_ev OSM_FILENAME)
  # Steht in Anführungszeichen in der .env — abziehen, sonst kommt bei jeder
  # Neukonfiguration eine Schicht dazu (""-Xmx8g …"" liest Compose als leer).
  PREV_JAVA_OPTS=$(_ev JAVA_OPTS | sed -E 's/^"+//; s/"+$//')
  PREV_LICENSE=$(_ev LICENSE_KEY)
  PREV_GH_TOKEN=$(_ev GITHUB_TOKEN)
fi

prompt "Domain (z.B. convoy.example.com)" "${PREV_DOMAIN:-}" DOMAIN
prompt "E-Mail für Let's Encrypt" "${PREV_EMAIL:-}" ACME_EMAIL

if [[ -n "$PREV_DB_PASS" ]]; then
  printf "Datenbankpasswort [Enter = bestehendes beibehalten]: " >/dev/tty
  read -rs _new_pw </dev/tty; echo >/dev/tty
  if [[ -z "$_new_pw" ]]; then
    DB_PASSWORD="$PREV_DB_PASS"
  else
    while true; do
      printf "Passwort bestätigen: " >/dev/tty
      read -rs _new_pw2 </dev/tty; echo >/dev/tty
      [[ -n "$_new_pw" && "$_new_pw" == "$_new_pw2" ]] && break
      echo "  Passwörter stimmen nicht überein oder leer. Erneut versuchen."
      printf "Datenbankpasswort: " >/dev/tty
      read -rs _new_pw </dev/tty; echo >/dev/tty
    done
    DB_PASSWORD="$_new_pw"
  fi
else
  prompt_secret "Datenbankpasswort" DB_PASSWORD
fi

echo ""
echo "OSM-Region wählen:"
echo "  1) DACH: DE+AT+CH+LI (~5,5 GB)"
echo "  2) Deutschland       (~4 GB)"
echo "  3) Bayern            (~1 GB)"
echo "  4) Berlin            (~30 MB, für Tests)"
echo "  5) Eigene URL eingeben"
if [[ -n "$PREV_OSM_FILE" ]]; then
  read -rp "Auswahl [Enter = beibehalten: $PREV_OSM_FILE]: " OSM_CHOICE </dev/tty
else
  read -rp "Auswahl [1]: " OSM_CHOICE </dev/tty
fi

if [[ -z "$OSM_CHOICE" && -n "$PREV_OSM_FILE" ]]; then
  OSM_URL="$PREV_OSM_URL"
  OSM_FILE="$PREV_OSM_FILE"
  JAVA_OPTS="${PREV_JAVA_OPTS:--Xmx4g -Xms1g -XX:+UseG1GC}"
else
  OSM_CHOICE="${OSM_CHOICE:-1}"
  case "$OSM_CHOICE" in
    1) OSM_URL="https://download.geofabrik.de/europe/dach-latest.osm.pbf"
       OSM_FILE="dach-latest.osm.pbf"
       JAVA_OPTS="-Xmx8g -Xms1g -XX:+UseG1GC" ;;
    2) OSM_URL="https://download.geofabrik.de/europe/germany-latest.osm.pbf"
       OSM_FILE="germany-latest.osm.pbf"
       JAVA_OPTS="-Xmx6g -Xms1g -XX:+UseG1GC" ;;
    3) OSM_URL="https://download.geofabrik.de/europe/germany/bayern-latest.osm.pbf"
       OSM_FILE="bayern-latest.osm.pbf"
       JAVA_OPTS="-Xmx3g -Xms512m -XX:+UseG1GC" ;;
    4) OSM_URL="https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf"
       OSM_FILE="berlin-latest.osm.pbf"
       JAVA_OPTS="-Xmx1g -Xms256m -XX:+UseG1GC" ;;
    5) prompt "OSM-Download-URL" "" OSM_URL
       OSM_FILE="$(basename "$OSM_URL")"
       JAVA_OPTS="-Xmx4g -Xms1g -XX:+UseG1GC" ;;
    *) echo "FEHLER: Ungültige Auswahl '$OSM_CHOICE'."; exit 1 ;;
  esac
fi

# Lizenzschlüssel — optional. Bei einer Neukonfiguration bleibt ein
# vorhandener Wert mit Enter erhalten.
echo ""
if [[ -n "$PREV_LICENSE" ]]; then
  read -rp "Lizenzschlüssel [Enter = bestehenden beibehalten]: " LICENSE_KEY </dev/tty
  LICENSE_KEY="${LICENSE_KEY:-$PREV_LICENSE}"
else
  read -rp "Lizenzschlüssel [Enter = Demo-Modus]: " LICENSE_KEY </dev/tty
fi

# Kein GitHub-Token: Das Repository ist öffentlich, Updater und Backend lesen
# die GitHub-API auch ohne. Ein Token hebt nur das Rate-Limit (60 → 5000
# Anfragen/Stunde je IP) und lässt sich bei Bedarf im Admin-Panel hinterlegen.
# Ein vorhandener Eintrag aus einer früheren Installation bleibt erhalten.
GITHUB_TOKEN="${PREV_GH_TOKEN:-}"

# JWT_SECRET beibehalten oder neu generieren
JWT_SECRET="${PREV_JWT:-$(openssl rand -hex 32)}"
mkdir -p "$INSTALL_DIR"

# Docker (Daemon läuft als root) kann Dateien und Verzeichnisse im Install-Dir
# als root anlegen. Ownership einmalig auf den aktuellen User zurücksetzen,
# damit alle nachfolgenden Operationen ohne sudo laufen.
sudo chown -R "$(id -u):$(id -g)" "$INSTALL_DIR"

# Download-Ziele bereinigen (jetzt als normaler User möglich)
rm -rf "$INSTALL_DIR/docker-compose.yml"

mkdir -p "$INSTALL_DIR/caddy"

echo ""
echo "→ Stack-Konfiguration herunterladen..."
curl -sSfL "$STACK_URL" -o "$INSTALL_DIR/docker-compose.yml" \
  || { echo "FEHLER: Stack-Datei konnte nicht heruntergeladen werden."; exit 1; }
curl -sSfL "$CADDY_ENTRYPOINT_URL" -o "$INSTALL_DIR/caddy/entrypoint.sh" \
  || { echo "FEHLER: Caddy-Entrypoint konnte nicht heruntergeladen werden."; exit 1; }
chmod +x "$INSTALL_DIR/caddy/entrypoint.sh"

# .env schreiben — restriktive Rechte, da DB-Passwort und JWT_SECRET enthalten.
( umask 077; : > "$INSTALL_DIR/.env" )
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
JAVA_OPTS="${JAVA_OPTS}"
BACKEND_IMAGE=ghcr.io/retttechsolutions/convoyplan/backend:latest
FRONTEND_IMAGE=ghcr.io/retttechsolutions/convoyplan/frontend:latest
GRAPHHOPPER_IMAGE=ghcr.io/retttechsolutions/convoyplan/graphhopper:latest
UPDATER_IMAGE=ghcr.io/retttechsolutions/convoyplan/updater:latest
REGION_MERGE_IMAGE=ghcr.io/retttechsolutions/convoyplan/osmium:latest
GITHUB_REPO=RettTechSolutions/ConvoyPlan
# Betriebsart: selfhost = eigene Instanz einer Organisation. Meldungen aus der
# Anwendung gehen zusätzlich an den Hersteller (CENTRAL_URL= leer schaltet das ab).
INSTANCE_MODE=${PREV_INSTANCE_MODE:-selfhost}
# Interne Ports (Docker-Netzwerk, nicht nach außen exponiert — bei Bedarf anpassen)
FRONTEND_PORT=3000
BACKEND_PORT=8000
# Auto-Updater: Pfad zu dieser Compose-Datei auf dem HOST (wird ins Updater-Image gemountet)
STACK_FILE_PATH=${INSTALL_DIR}/docker-compose.yml
# Caddy-Entrypoint-Skript auf dem HOST (wird per Bind-Mount in den Caddy-Container geladen)
CADDY_ENTRYPOINT_PATH=${INSTALL_DIR}/caddy/entrypoint.sh
# Docker-Compose-Projektname — muss mit dem Namen übereinstimmen, den Compose beim Start verwendet
COMPOSE_PROJECT_NAME=convoyplan
ENVEOF
if [[ -n "$LICENSE_KEY" ]]; then
  echo "LICENSE_KEY=${LICENSE_KEY}" >> "$INSTALL_DIR/.env"
else
  echo "# Lizenzschlüssel nach dem Setup im Admin-Panel unter System → Lizenz eintragen" >> "$INSTALL_DIR/.env"
  echo "# LICENSE_KEY=" >> "$INSTALL_DIR/.env"
fi
if [[ -n "$GITHUB_TOKEN" ]]; then
  echo "GITHUB_TOKEN=${GITHUB_TOKEN}" >> "$INSTALL_DIR/.env"
fi
chmod 600 "$INSTALL_DIR/.env"

# Stack starten
_images_ziehen "$INSTALL_DIR"

_konvoi "ConvoyPlan starten" - \
  docker compose --project-directory "$INSTALL_DIR" up -d || true

_install_watchdog "$INSTALL_DIR"

echo ""
# GraphHopper-Hinweis je nach Region (max. 54 ASCII-Zeichen für saubere Box)
if [[ "$OSM_FILE" == *"dach-latest"* ]]; then
  GH_HINT1="! Routing-Graph DACH: ca. 60-120 Min. Ladezeit"
  GH_HINT2="  Voraussetzung: mind. 8 GB RAM verfuegbar"
elif [[ "$OSM_FILE" == *"germany-latest"* ]]; then
  GH_HINT1="! Routing-Graph DE: ca. 45-90 Min. Ladezeit"
  GH_HINT2="  Voraussetzung: mind. 6 GB RAM verfuegbar"
elif [[ "$OSM_FILE" == *"bayern"* ]]; then
  GH_HINT1="! Routing-Graph BY: ca. 10-20 Min. Ladezeit"
  GH_HINT2="  Voraussetzung: mind. 3 GB RAM verfuegbar"
else
  GH_HINT1="i GraphHopper laedt im Hintergrund"
  GH_HINT2="  Routing steht danach bereit"
fi

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ConvoyPlan wurde gestartet!                             ║"
printf "║  Setup-Wizard: https://%-34s║\n" "${DOMAIN}/setup"
echo "╠══════════════════════════════════════════════════════════╣"
printf "║  %-56s║\n" "$GH_HINT1"
printf "║  %-56s║\n" "$GH_HINT2"
echo "║  Logs:  docker compose logs -f graphhopper               ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Lizenz: Admin-Panel > System > Lizenz nach dem Setup    ║"
echo "║  Anfrage: anfrage@convoyplan.de (mit Instanz-UUID)       ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
