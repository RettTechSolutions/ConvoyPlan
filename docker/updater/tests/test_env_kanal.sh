#!/usr/bin/env bash
# Prueft docker/updater/env-kanal.sh: die .env des Hosts traegt die Image-Tags
# des Kanals, den der Updater tatsaechlich deployt.
#
# Anlass (2026-10-09): Eine Nightly-Instanz zog per `docker compose pull` von
# Hand das Stable-Image aus der .env — aelter als der laufende Stand, und der
# Graph musste ein weiteres Mal komplett neu gebaut werden. Der Updater setzt
# den Kanal nur in seiner eigenen Umgebung durch; die .env blieb auf :latest.
#
# Teil 1 prueft die Umschreibung als reine Textverarbeitung. Teil 2 den Weg
# ueber den Hilfscontainer: `docker` ist eine Attrappe, die `-v <dir>:/stack`
# auf ein Temp-Verzeichnis abbildet und das `sh -c` dort ausfuehrt — so laeuft
# der echte Lese- und Schreibbefehl gegen eine echte Datei, ohne Docker.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
UPDATER_DIR="$(cd "$HERE/.." && pwd)"
FAILED=0

check() {
    if [ "$2" = "$3" ]; then
        echo "ok   — $1"
    else
        echo "FAIL — $1"
        echo "       erwartet: $(printf '%q' "$3")"
        echo "       bekam:    $(printf '%q' "$2")"
        FAILED=1
    fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

LOG="$TMP/log.txt"
log() { echo "$*" >> "$LOG"; }
# shellcheck source=../env-kanal.sh
. "$UPDATER_DIR/env-kanal.sh"

P="ghcr.io/retttechsolutions/convoyplan"

# ── Teil 1: die Umschreibung ────────────────────────────────────────────────
EINGABE="# ConvoyPlan
POSTGRES_PASSWORD=geheim=mit=gleich
BACKEND_IMAGE=$P/backend:latest
FRONTEND_IMAGE=$P/frontend:latest
GRAPHHOPPER_IMAGE=$P/graphhopper:latest
UPDATER_IMAGE=$P/updater:latest
REGION_MERGE_IMAGE=$P/osmium:latest
DOCKER_PROXY_IMAGE=ghcr.io/tecnativa/docker-socket-proxy:v0.5.0
JAVA_OPTS=-Xmx6g -Xms1g -XX:+UseG1GC"

ERWARTET="# ConvoyPlan
POSTGRES_PASSWORD=geheim=mit=gleich
BACKEND_IMAGE=$P/backend:nightly
FRONTEND_IMAGE=$P/frontend:nightly
GRAPHHOPPER_IMAGE=$P/graphhopper:nightly
UPDATER_IMAGE=$P/updater:nightly
REGION_MERGE_IMAGE=$P/osmium:nightly
DOCKER_PROXY_IMAGE=ghcr.io/tecnativa/docker-socket-proxy:v0.5.0
JAVA_OPTS=-Xmx6g -Xms1g -XX:+UseG1GC"

check "alle fuenf Images auf :nightly, alles andere Byte fuer Byte gleich" \
    "$(printf '%s\n' "$EINGABE" | _env_kanal_umschreiben nightly)" "$ERWARTET"

check "zurueck auf Stable ergibt wieder die Ausgangsdatei" \
    "$(printf '%s\n' "$ERWARTET" | _env_kanal_umschreiben latest)" "$EINGABE"

check "eine gepinnte Version wird auf den Kanal gezogen (wie _apply_channel_images)" \
    "$(echo "GRAPHHOPPER_IMAGE=$P/graphhopper:v2026.7.3" | _env_kanal_umschreiben beta)" \
    "GRAPHHOPPER_IMAGE=$P/graphhopper:beta"

# Was nicht eindeutig ein Image dieses Projekts mit Tag ist, bleibt stehen —
# lieber nicht anfassen als eine fremde Angabe kaputt umschreiben.
for zeile in \
    "GRAPHHOPPER_IMAGE=registry.example.org/mirror/graphhopper:latest" \
    "GRAPHHOPPER_IMAGE=$P/graphhopper@sha256:0123456789abcdef" \
    "GRAPHHOPPER_IMAGE=\"$P/graphhopper:latest\"" \
    "GRAPHHOPPER_IMAGE=$P/graphhopper" \
    "GRAPHHOPPER_IMAGE=" \
    "# GRAPHHOPPER_IMAGE=$P/graphhopper:latest" \
    "MY_GRAPHHOPPER_IMAGE=$P/graphhopper:latest"; do
    check "bleibt unveraendert: $zeile" \
        "$(echo "$zeile" | _env_kanal_umschreiben nightly)" "$zeile"
done

check "letzte Zeile ohne Zeilenende geht nicht verloren" \
    "$(printf 'A=1\nGRAPHHOPPER_IMAGE=%s/graphhopper:latest' "$P" | _env_kanal_umschreiben nightly)" \
    "$(printf 'A=1\nGRAPHHOPPER_IMAGE=%s/graphhopper:nightly' "$P")"

# ── Teil 2: Lesen und Schreiben ueber den Hilfscontainer ────────────────────
mkdir -p "$TMP/bin"
cat > "$TMP/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
# Attrappe: `docker run --rm [-i] -v <dir>:/stack[:ro] <image> sh -c <skript>`
# fuehrt <skript> mit /stack -> <dir> aus. Alles andere: Exit 0, keine Ausgabe.
echo "docker $*" >> "$DOCKER_CALLS"
[ "${1:-}" = "run" ] || exit 0
dir=""; skript=""; prev=""
for a in "$@"; do
    case "$prev" in
        -v) dir="${a%%:/stack*}" ;;
        -c) skript="$a" ;;
    esac
    prev="$a"
done
[ -n "$dir" ] && [ -n "$skript" ] || exit 0
sh -c "${skript//\/stack/$dir}"
DOCKER
chmod +x "$TMP/bin/docker"
export PATH="$TMP/bin:$PATH"
export DOCKER_CALLS="$TMP/docker_calls.txt"

INST="$TMP/convoyplan"; mkdir -p "$INST"
: > "$INST/docker-compose.yml"
printf '%s\n' "$EINGABE" > "$INST/.env"
chmod 600 "$INST/.env"
export STACK_FILE_PATH="$INST/docker-compose.yml"

: > "$LOG"; : > "$DOCKER_CALLS"
_env_kanal_abgleichen nightly
check "die .env auf dem Host traegt danach die Nightly-Tags" "$(cat "$INST/.env")" "$ERWARTET"
check "Rechte der .env bleiben 600 (Geheimnisse darin)" "$(stat -c %a "$INST/.env")" "600"
grep -q "auf den Kanal-Tag :nightly gesetzt" "$LOG"; check "Aenderung wird geloggt" "$?" "0"

: > "$LOG"; : > "$DOCKER_CALLS"
_env_kanal_abgleichen nightly
check "schon passend: nur gelesen, nicht geschrieben" "$(grep -c '^docker run' "$DOCKER_CALLS")" "1"
check "schon passend: nichts geloggt" "$(wc -l < "$LOG" | tr -d ' ')" "0"

rm -f "$INST/.env"
: > "$LOG"; : > "$DOCKER_CALLS"
_env_kanal_abgleichen nightly
check "ohne .env: keine angelegt" "$([ -e "$INST/.env" ] && echo da || echo fehlt)" "fehlt"
check "ohne .env: kein Schreibversuch" "$(grep -c '^docker run' "$DOCKER_CALLS")" "1"

: > "$DOCKER_CALLS"
STACK_FILE_PATH=/dev/null _env_kanal_abgleichen nightly
check "STACK_FILE_PATH=/dev/null (Altinstallation): gar kein Hilfscontainer" \
    "$(wc -l < "$DOCKER_CALLS" | tr -d ' ')" "0"

# ── Teil 3: die Verdrahtung ─────────────────────────────────────────────────
# Ohne `source` im Updater und ohne COPY im Image waere alles oben totes Holz.
grep -q '^source /env-kanal.sh$' "$UPDATER_DIR/update-images.sh"
check "update-images.sh bindet env-kanal.sh ein" "$?" "0"
grep -q '^    _env_kanal_pruefen$' "$UPDATER_DIR/update-images.sh"
check "die Hauptschleife ruft den Abgleich" "$?" "0"
grep -q '^COPY env-kanal.sh /env-kanal.sh$' "$UPDATER_DIR/Dockerfile"
check "das Updater-Image enthaelt env-kanal.sh" "$?" "0"

exit $FAILED
