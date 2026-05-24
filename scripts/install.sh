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
read -rp "Auswahl [1]: " OSM_CHOICE </dev/tty
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

LICENSE_KEY=""
GITHUB_TOKEN=""
read -rp "Lizenzschlüssel [Enter = Demo-Modus]: " LICENSE_KEY </dev/tty 2>/dev/null || true
read -rp "GitHub Token für Auto-Updater [Enter = überspringen]: " GITHUB_TOKEN </dev/tty 2>/dev/null || true

# JWT_SECRET generieren
JWT_SECRET="$(openssl rand -hex 32)"

# Installationsverzeichnis anlegen
if [[ -d "$INSTALL_DIR" && -f "$INSTALL_DIR/.env" ]]; then
  read -rp "Verzeichnis '$INSTALL_DIR' mit .env existiert. Überschreiben? [j/N]: " OVERWRITE </dev/tty || true
  if [[ "${OVERWRITE,,}" != "j" ]]; then
    echo "Abgebrochen."
    exit 0
  fi
fi
mkdir -p "$INSTALL_DIR"

# Stack-Datei herunterladen
echo ""
echo "→ Stack-Konfiguration herunterladen..."
curl -sSfL "$STACK_URL" -o "$INSTALL_DIR/docker-compose.yml" \
  || { echo "FEHLER: Stack-Datei konnte nicht heruntergeladen werden."; rm -f "$INSTALL_DIR/docker-compose.yml"; exit 1; }

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
JAVA_OPTS="-Xmx2g -Xms512m -XX:+UseG1GC"
BACKEND_IMAGE=ghcr.io/retttechsolutions/convoyplan-backend:latest
FRONTEND_IMAGE=ghcr.io/retttechsolutions/convoyplan-frontend:latest
GRAPHHOPPER_IMAGE=ghcr.io/retttechsolutions/convoyplan-graphhopper:latest
GITHUB_REPO=RettTechSolutions/ConvoyPlan
ENVEOF

[[ -n "${LICENSE_KEY:-}" ]] && echo "LICENSE_KEY=${LICENSE_KEY}" >> "$INSTALL_DIR/.env"
[[ -n "${GITHUB_TOKEN:-}" ]] && echo "GITHUB_TOKEN=${GITHUB_TOKEN}" >> "$INSTALL_DIR/.env"

# Stack starten
echo ""
echo "→ Images herunterladen (kann einige Minuten dauern)..."
docker compose --project-directory "$INSTALL_DIR" pull

echo ""
echo "→ ConvoyPlan starten..."
docker compose --project-directory "$INSTALL_DIR" up -d

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ConvoyPlan läuft!                                       ║"
printf "║  Setup-Wizard: https://%-34s║\n" "${DOMAIN}/setup"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
