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
     OSM_FILE="germany-latest.osm.pbf"
     JAVA_OPTS="-Xmx6g -Xms1g -XX:+UseG1GC" ;;
  2) OSM_URL="https://download.geofabrik.de/europe/germany/bayern-latest.osm.pbf"
     OSM_FILE="bayern-latest.osm.pbf"
     JAVA_OPTS="-Xmx3g -Xms512m -XX:+UseG1GC" ;;
  3) OSM_URL="https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf"
     OSM_FILE="berlin-latest.osm.pbf"
     JAVA_OPTS="-Xmx1g -Xms256m -XX:+UseG1GC" ;;
  4) prompt "OSM-Download-URL" "" OSM_URL
     OSM_FILE="$(basename "$OSM_URL")"
     JAVA_OPTS="-Xmx4g -Xms1g -XX:+UseG1GC" ;;
  *) echo "FEHLER: Ungültige Auswahl '$OSM_CHOICE'."; exit 1 ;;
esac

LICENSE_KEY=""
GITHUB_TOKEN=""
printf "Lizenzschlüssel [Enter = Demo-Modus]: " >/dev/tty
read -r LICENSE_KEY </dev/tty || true
printf "GitHub Token für Auto-Updater [Enter = überspringen]: " >/dev/tty
read -r GITHUB_TOKEN </dev/tty || true

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

# Docker erstellt fehlende Bind-Mount-Quellen als root-eigene Verzeichnisse.
# Vor dem Download bereinigen; sudo nötig wenn Docker als root lief.
_cleanup() {
  rm -rf "$@" 2>/dev/null && return
  echo "  → sudo erforderlich (Docker-Artefakte gehören root)..."
  sudo rm -rf "$@" || {
    echo "FEHLER: Kann alte Docker-Artefakte nicht entfernen."
    echo "       Manuell ausführen: sudo rm -rf $*"
    exit 1
  }
}
_cleanup "$INSTALL_DIR/docker-compose.yml" "$INSTALL_DIR/caddy/entrypoint.sh"
mkdir -p "$INSTALL_DIR/caddy"

# Stack-Datei und Caddy-Entrypoint herunterladen
echo ""
echo "→ Stack-Konfiguration herunterladen..."
curl -sSfL "$STACK_URL" -o "$INSTALL_DIR/docker-compose.yml" \
  || { echo "FEHLER: Stack-Datei konnte nicht heruntergeladen werden."; exit 1; }
curl -sSfL "$REPO_RAW/caddy/entrypoint.sh" -o "$INSTALL_DIR/caddy/entrypoint.sh" \
  || { echo "FEHLER: Caddy-Entrypoint konnte nicht heruntergeladen werden."; exit 1; }
chmod +x "$INSTALL_DIR/caddy/entrypoint.sh"

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
JAVA_OPTS=${JAVA_OPTS}
BACKEND_IMAGE=ghcr.io/retttechsolutions/convoyplan/backend:latest
FRONTEND_IMAGE=ghcr.io/retttechsolutions/convoyplan/frontend:latest
GRAPHHOPPER_IMAGE=ghcr.io/retttechsolutions/convoyplan/graphhopper:latest
GITHUB_REPO=RettTechSolutions/ConvoyPlan
# Interne Ports (Docker-Netzwerk, nicht nach außen exponiert — bei Bedarf anpassen)
FRONTEND_PORT=3000
BACKEND_PORT=8000
ENVEOF

[[ -n "${LICENSE_KEY:-}" ]] && echo "LICENSE_KEY=${LICENSE_KEY}" >> "$INSTALL_DIR/.env"
[[ -n "${GITHUB_TOKEN:-}" ]] && echo "GITHUB_TOKEN=${GITHUB_TOKEN}" >> "$INSTALL_DIR/.env"

# Stack starten
echo ""
echo "→ Images herunterladen (kann einige Minuten dauern)..."
docker compose --project-directory "$INSTALL_DIR" pull

echo ""
echo "→ ConvoyPlan starten..."
docker compose --project-directory "$INSTALL_DIR" up -d || true

echo ""
# GraphHopper-Hinweis je nach Region
if [[ "$OSM_FILE" == *"germany-latest"* ]]; then
  GH_HINT="⚠  GraphHopper (Deutschland) braucht 45-90 Min. und 6 GB RAM."
elif [[ "$OSM_FILE" == *"bayern"* ]]; then
  GH_HINT="⚠  GraphHopper (Bayern) braucht ca. 10-20 Min. und 3 GB RAM."
else
  GH_HINT="ℹ  GraphHopper lädt im Hintergrund. Routing ist danach verfügbar."
fi

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ConvoyPlan wurde gestartet!                             ║"
printf "║  Setup-Wizard: https://%-34s║\n" "${DOMAIN}/setup"
echo "╠══════════════════════════════════════════════════════════╣"
printf "║  %-56s║\n" "$GH_HINT"
echo "║  Fortschritt: docker compose logs -f graphhopper         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
