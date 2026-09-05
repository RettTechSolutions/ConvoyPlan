#!/usr/bin/env bash
# Prueft _head_size() aus docker/updater/switch-region.sh — die Groessenabfrage
# eines Geofabrik-Extracts.
#
# WARUM IM CONTAINER: Der Fehler, den dieser Test absichert, existiert nur
# unter busybox-awk, und genau das ist das awk des Updater-Images (Alpine).
# Die frueherre Fassung endete mit `printf "%d", v+0`; busybox castet den
# intern als double gehaltenen Wert dabei auf `int`, also 32 Bit
# (editors/awk.c, awk_printf: `s = xasprintf(s, (int)d);` — mit TODO an
# derselben Stelle). DACH ist 6.215.032.253 Bytes gross, liegt also ueber
# 2^31; der Cast ist in C undefiniert und liefert auf x86-64 -2147483648.
# Folge in Produktion: JEDER Wechsel auf eine Region ueber 2 GB scheiterte an
# "Extract nicht abrufbar", obwohl die Datei einwandfrei erreichbar war.
#
# Auf einem Entwicklungsrechner (BWK awk) und auf dem CI-Runner (mawk)
# rechnen beide Fassungen richtig — ein Test dort waere gruen und wertlos
# gewesen. Deshalb laeuft dieser hier im echten Basisimage des Updaters.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
UPDATER_DIR="$(cd "$HERE/.." && pwd)"

if ! docker info >/dev/null 2>&1; then
    echo "SKIP — Docker-Daemon nicht erreichbar, Test übersprungen."
    exit 0
fi

docker run --rm \
    -v "${UPDATER_DIR}/switch-region.sh:/switch-region.sh:ro" \
    -i docker:cli sh -s <<'INNER'
set -u
FAILED=0
check() {
    if [ "$2" = "$3" ]; then
        echo "ok   — $1"
    else
        echo "FAIL — $1: erwartet '$3', bekam '$2'"
        FAILED=1
    fi
}

# Beleg, dass wir wirklich in der Umgebung messen, um die es geht. Ohne diese
# Zusicherung koennte der Test unbemerkt unter einem anderen awk laufen und
# gruen sein, ohne irgendetwas zu beweisen.
command -v busybox >/dev/null 2>&1 && r=ja || r=nein
check "Test laeuft unter busybox (das awk des Updater-Images)" "$r" "ja"

# Zur Einordnung im Protokoll, bewusst KEINE Zusicherung: Sollte busybox das
# eines Tages beheben, soll dieser Test nicht deswegen rot werden.
echo "     Hinweis: printf \"%d\", 6215032253 ergibt hier: $(awk 'BEGIN{printf "%d", 6215032253}')"

# Die ECHTE Funktion herausschneiden statt sie nachzubauen.
sed -n '/^_head_size() {/,/^}/p' /switch-region.sh > /fn.sh
grep -q '^_head_size() {' /fn.sh && grep -q '^}' /fn.sh && r=ja || r=nein
check "_head_size vollstaendig aus switch-region.sh geschnitten" "$r" "ja"

# curl-Stub: liefert einen realistischen Kopf-Block inklusive Weiterleitung
# und CRLF — Geofabrik beantwortet -latest-URLs immer mit 302.
mkdir -p /stub
cat > /stub/curl <<'STUB'
#!/bin/sh
[ -n "${STUB_NO_LENGTH:-}" ] && { printf 'HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n\r\n'; exit 0; }
printf 'HTTP/1.1 302 Found\r\nLocation: https://download.geofabrik.de/europe/dach-260904.osm.pbf\r\n\r\nHTTP/1.1 200 OK\r\nContent-Length: %s\r\n\r\n' "${STUB_LEN:-0}"
STUB
chmod +x /stub/curl
export PATH="/stub:$PATH"
. /fn.sh

# ── Der eigentliche Fall: DACH, 6,2 GB, ueber 2^31 ────────────────────────
check "Groesse ueber 2^31 wird exakt durchgereicht" \
      "$(STUB_LEN=6215032253 _head_size https://download.geofabrik.de/europe/dach-latest.osm.pbf)" \
      "6215032253"

# ── Regressionsschutz: kleine Regionen bleiben unveraendert ───────────────
check "Berlin-Groesse unveraendert" \
      "$(STUB_LEN=99195978 _head_size https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf)" \
      "99195978"

# ── Genau an der Grenze ───────────────────────────────────────────────────
check "2^31 - 1 (letzter Wert, den die alte Fassung noch konnte)" \
      "$(STUB_LEN=2147483647 _head_size https://x/y-latest.osm.pbf)" "2147483647"
check "2^31 (erster Wert, an dem sie brach)" \
      "$(STUB_LEN=2147483648 _head_size https://x/y-latest.osm.pbf)" "2147483648"

# ── Fehlerfaelle muessen weiterhin 0 ergeben ──────────────────────────────
# 0 ist das Signal fuer "nicht abrufbar"; der Aufrufer bricht daraufhin ab.
check "Antwort ohne Content-Length ergibt 0" \
      "$(STUB_NO_LENGTH=1 _head_size https://x/y-latest.osm.pbf)" "0"
check "unsinniger Wert ergibt 0" \
      "$(STUB_LEN=keine-zahl _head_size https://x/y-latest.osm.pbf)" "0"

exit $FAILED
INNER
