#!/usr/bin/env bash
set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/RettTechSolutions/ConvoyPlan/main"
STACK_URL="$REPO_RAW/docker-compose.yml"
CADDY_ENTRYPOINT_URL="$REPO_RAW/caddy/entrypoint.sh"
WATCHDOG_URL="$REPO_RAW/scripts/updater-watchdog.sh"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║      ConvoyPlan Installer v0.8.5         ║"
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

_ev() { grep -m1 "^${1}=" "$INSTALL_DIR/.env" 2>/dev/null | cut -d= -f2- || true; }

if [[ -f "$INSTALL_DIR/.env" ]] && \
   [[ -n "$(_ev POSTGRES_PASSWORD)" ]] && \
   [[ -n "$(_ev DOMAIN)" ]]; then

  echo ""
  echo "Bestehende ConvoyPlan-Installation in '$INSTALL_DIR' gefunden."
  echo "  [J] Nur aktualisieren — Einstellungen beibehalten  (empfohlen)"
  echo "  [n] Neu konfigurieren — Werte als Vorauswahl laden"
  read -rp "Auswahl [J/n]: " _upd </dev/tty || true

  if [[ "${_upd,,}" != "n" ]]; then
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

    sudo chown -R "$(id -u):$(id -g)" "$INSTALL_DIR"
    rm -f "$INSTALL_DIR/docker-compose.yml"
    mkdir -p "$INSTALL_DIR/caddy"

    echo "→ Neueste Stack-Konfiguration herunterladen..."
    curl -sSfL "$STACK_URL" -o "$INSTALL_DIR/docker-compose.yml" \
      || { echo "FEHLER: Stack-Datei konnte nicht heruntergeladen werden."; exit 1; }
    curl -sSfL "$CADDY_ENTRYPOINT_URL" -o "$INSTALL_DIR/caddy/entrypoint.sh" \
      || { echo "FEHLER: Caddy-Entrypoint konnte nicht heruntergeladen werden."; exit 1; }
    chmod +x "$INSTALL_DIR/caddy/entrypoint.sh"

    echo "→ Images aktualisieren..."
    docker compose --project-directory "$INSTALL_DIR" pull

    echo "→ Verwaiste Updater-Container aufräumen..."
    _cleanup_orphan_updaters "$(_ev COMPOSE_PROJECT_NAME)"

    echo "→ ConvoyPlan neu starten..."
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
  PREV_OSM_URL=$(_ev OSM_DOWNLOAD_URL)
  PREV_OSM_FILE=$(_ev OSM_FILENAME)
  PREV_JAVA_OPTS=$(_ev JAVA_OPTS)
  echo "✓ Bestehende Werte geladen."
  echo ""

elif [[ -f "$INSTALL_DIR/.env" ]]; then
  # Unvollständige .env — Werte als Vorauswahl laden, vollständige Konfiguration abfragen
  PREV_DOMAIN=$(_ev DOMAIN)
  PREV_EMAIL=$(_ev ACME_EMAIL)
  PREV_DB_PASS=$(_ev POSTGRES_PASSWORD)
  PREV_JWT=$(_ev JWT_SECRET)
  PREV_OSM_URL=$(_ev OSM_DOWNLOAD_URL)
  PREV_OSM_FILE=$(_ev OSM_FILENAME)
  PREV_JAVA_OPTS=$(_ev JAVA_OPTS)
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
# Interne Ports (Docker-Netzwerk, nicht nach außen exponiert — bei Bedarf anpassen)
FRONTEND_PORT=3000
BACKEND_PORT=8000
# Auto-Updater: Pfad zu dieser Compose-Datei auf dem HOST (wird ins Updater-Image gemountet)
STACK_FILE_PATH=${INSTALL_DIR}/docker-compose.yml
# Caddy-Entrypoint-Skript auf dem HOST (wird per Bind-Mount in den Caddy-Container geladen)
CADDY_ENTRYPOINT_PATH=${INSTALL_DIR}/caddy/entrypoint.sh
# Docker-Compose-Projektname — muss mit dem Namen übereinstimmen, den Compose beim Start verwendet
COMPOSE_PROJECT_NAME=convoyplan
# Lizenzschlüssel nach dem Setup im Admin-Panel unter System → Lizenz eintragen
# LICENSE_KEY=
ENVEOF
chmod 600 "$INSTALL_DIR/.env"

# Stack starten
echo ""
echo "→ Images herunterladen (kann einige Minuten dauern)..."
docker compose --project-directory "$INSTALL_DIR" pull

echo ""
echo "→ ConvoyPlan starten..."
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
