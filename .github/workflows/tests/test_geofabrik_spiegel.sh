#!/usr/bin/env bash
# Prueft den Geofabrik-Spiegel des Jobs `region-switch` (.github/region-spiegel/).
#
# Der Spiegel ersetzt im Job download.geofabrik.de. Was der Updater dort
# braucht, prueft dieser Test ohne Docker an den echten Dateien:
# Groesse per HEAD, .md5 im Geofabrik-Format, die Bytes selbst, 404 fuer
# Unbekanntes (switch-region.sh laedt mit `curl -f`), Vertrauen nur mit dem
# Buendel — und dass die Adresse, die switch-region.sh fuer einen Regionspfad
# baut, und die, die der Job anfordert, auf dem Spiegel liegen. Ohne Letzteres
# liefe der Job nach einer Schemaaenderung gegen eine 404 des Spiegels und
# meldete einen Fehler im Updater.
set -uo pipefail
# Ein Proxy in der Umgebung umginge --resolve; der Spiegel ist lokal.
unset https_proxy HTTPS_PROXY http_proxy HTTP_PROXY all_proxy ALL_PROXY

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/../../.."
SPIEGEL="$ROOT/.github/region-spiegel"
FAILED=0

ok()  { echo "ok   — $1"; }
bad() { echo "FAIL — $1"; FAILED=1; }

for werkzeug in python3 curl openssl md5sum; do
    if ! command -v "$werkzeug" >/dev/null 2>&1; then
        echo "SKIP — $werkzeug fehlt, Test uebersprungen."
        exit 0
    fi
done

WORK="$(mktemp -d)"
PID=""
trap '[ -n "$PID" ] && kill "$PID" 2>/dev/null; rm -rf "$WORK"' EXIT

# Ein Extract mit Inhalt, der sich vom 404-Text unterscheidet.
head -c 300000 /dev/urandom > "$WORK/berlin.pbf"

if bash "$SPIEGEL/vorbereiten.sh" "$WORK/spiegel" europe/germany/berlin "$WORK/berlin.pbf" >"$WORK/vorb.log" 2>&1; then
    ok "vorbereiten.sh laeuft durch"
else
    bad "vorbereiten.sh scheitert: $(cat "$WORK/vorb.log")"
    exit 1
fi

DATEI="$WORK/spiegel/daten/europe/germany/berlin/berlin-latest.osm.pbf"
[ -f "$DATEI" ] && ok "Extract liegt im neuen Geofabrik-Schema" \
    || bad "Extract fehlt unter europe/germany/berlin/berlin-latest.osm.pbf"
[ ! -e "$WORK/spiegel/tls/ca.key" ] && ok "Schluessel der Test-CA ist weggeraeumt" \
    || bad "Schluessel der Test-CA liegt noch im Spiegel"

PORT=$(( 20000 + RANDOM % 20000 ))
python3 "$SPIEGEL/spiegel.py" "$WORK/spiegel/daten" \
    "$WORK/spiegel/tls/server.pem" "$WORK/spiegel/tls/server.key" "$PORT" \
    >"$WORK/server.log" 2>&1 &
PID=$!

# Wie im Updater: Name download.geofabrik.de, Vertrauen ueber CURL_CA_BUNDLE.
spiegel_curl() {
    CURL_CA_BUNDLE="$WORK/spiegel/tls/bundle.pem" \
        curl --resolve "download.geofabrik.de:$PORT:127.0.0.1" "$@"
}
basis="https://download.geofabrik.de:$PORT"

bereit=0
for _ in $(seq 1 50); do
    if spiegel_curl -fsS -o /dev/null -I "$basis/europe/germany/berlin/berlin-latest.osm.pbf" 2>/dev/null; then
        bereit=1; break
    fi
    sleep 0.1
done
if [ "$bereit" = 1 ]; then
    ok "Spiegel antwortet per TLS unter download.geofabrik.de"
else
    bad "Spiegel antwortet nicht: $(cat "$WORK/server.log")"
    exit 1
fi

url="$basis/europe/germany/berlin/berlin-latest.osm.pbf"

# Dieselbe Auswertung wie _head_size in switch-region.sh.
laenge="$(spiegel_curl -sSIL "$url" | awk 'tolower($1)=="content-length:"{v=$2} END{sub(/\r$/,"",v); print v}')"
[ "$laenge" = "$(wc -c < "$WORK/berlin.pbf" | tr -d ' ')" ] \
    && ok "HEAD meldet die Groesse des Extracts ($laenge Bytes)" \
    || bad "HEAD meldet '$laenge' statt $(wc -c < "$WORK/berlin.pbf") Bytes"

spiegel_curl -fsS -o "$WORK/geladen" "$url"
cmp -s "$WORK/geladen" "$WORK/berlin.pbf" && ok "GET liefert das Extract bytegleich" \
    || bad "GET liefert andere Bytes"

md5="$(spiegel_curl -fsS "$url.md5")"
[ "$(echo "$md5" | awk '{print $1}')" = "$(md5sum "$WORK/berlin.pbf" | awk '{print $1}')" ] \
    && [ "$(echo "$md5" | awk '{print $2}')" = "berlin-latest.osm.pbf" ] \
    && ok ".md5 im Geofabrik-Format (Hash, Dateiname)" \
    || bad ".md5 stimmt nicht: '$md5'"

code="$(spiegel_curl -s -o /dev/null -w '%{http_code}' "$basis/europe/germany/berlin-latest.osm.pbf")"
[ "$code" = 404 ] && ok "alte Adresse ergibt 404 wie bei Geofabrik (curl -f scheitert)" \
    || bad "unbekannte Adresse ergibt $code statt 404"

if curl -fsS -o /dev/null --resolve "download.geofabrik.de:$PORT:127.0.0.1" "$url" 2>/dev/null; then
    bad "ohne das Buendel wird dem Spiegel vertraut — die Test-CA steckt in den System-Wurzeln?"
else
    ok "ohne das Buendel wird dem Zertifikat nicht vertraut"
fi

# Die Adresse, die switch-region.sh baut — die Funktion aus dem Original.
awk '/^_geofabrik_url\(\) \{/{p=1} p{print} p&&/^\}/{exit}' \
    "$ROOT/docker/updater/switch-region.sh" > "$WORK/fn.sh"
if [ -s "$WORK/fn.sh" ]; then
    # shellcheck source=/dev/null
    . "$WORK/fn.sh"
    gebaut="$(_geofabrik_url europe/germany/berlin)"
    pfad="${gebaut#https://download.geofabrik.de}"
    [ -f "$WORK/spiegel/daten$pfad" ] \
        && ok "die Adresse aus switch-region.sh liegt auf dem Spiegel ($pfad)" \
        || bad "switch-region.sh baut $gebaut — auf dem Spiegel liegt das nicht"
else
    bad "_geofabrik_url in switch-region.sh nicht gefunden — Test und Updater sind auseinandergelaufen"
fi

# Die Adresse, die der Job anfordert — aus ci.yml.
angefordert="$(grep -o '"url":"https://download\.geofabrik\.de/[^"]*"' "$ROOT/.github/workflows/ci.yml" \
    | head -1 | sed 's/^"url":"https:\/\/download\.geofabrik\.de//; s/"$//')"
[ -n "$angefordert" ] && [ -f "$WORK/spiegel/daten$angefordert" ] \
    && ok "die Adresse der Anforderung in ci.yml liegt auf dem Spiegel ($angefordert)" \
    || bad "ci.yml fordert '$angefordert' an — auf dem Spiegel liegt das nicht"

grep -q "GET /europe/germany/berlin/berlin-latest.osm.pbf " "$WORK/server.log" \
    && ok "der Spiegel protokolliert den Download (Beleg im Job)" \
    || bad "kein GET im Protokoll des Spiegels: $(cat "$WORK/server.log")"

exit $FAILED
