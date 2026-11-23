#!/usr/bin/env bash
# Legt den Geofabrik-Spiegel fuer den Job `region-switch` an (siehe spiegel.py).
#
# Aufruf: vorbereiten.sh <ziel> <regionspfad> <extract> [<regionspfad> <extract> ...]
#   z. B. vorbereiten.sh "$RUNNER_TEMP/spiegel" europe/germany/berlin osm/berlin-latest.osm.pbf
#
# Ergebnis unter <ziel>:
#   daten/<pfad>/<name>-latest.osm.pbf       das Extract, wie Geofabrik es ablegt
#   daten/<pfad>/<name>-latest.osm.pbf.md5   "<hash>  <datei>", wie bei Geofabrik
#   tls/ca.pem, tls/server.pem, tls/server.key   Test-CA und Zertifikat fuer
#                                            download.geofabrik.de, zwei Tage gueltig
#   tls/bundle.pem                           System-Wurzeln + Test-CA, fuer
#                                            CURL_CA_BUNDLE im Updater
#
# Das Ablageschema ist das seit November 2026 (jede Region in ihrem eigenen
# Verzeichnis, siehe CLAUDE.md, "Geofabrik-Adressen") — dasselbe, das
# geofabrik.pbf_url und _geofabrik_url in switch-region.sh bauen.
set -euo pipefail

ziel="$1"; shift
[ $(( $# % 2 )) -eq 0 ] && [ $# -gt 0 ] || {
    echo "Aufruf: vorbereiten.sh <ziel> <regionspfad> <extract> [...]" >&2
    exit 2
}

mkdir -p "$ziel/daten" "$ziel/tls"

while [ $# -gt 0 ]; do
    pfad="$1"; extract="$2"; shift 2
    name="${pfad##*/}"
    [ -s "$extract" ] || { echo "Extract fehlt oder ist leer: $extract" >&2; exit 1; }
    dir="$ziel/daten/$pfad"
    mkdir -p "$dir"
    # Verlinken statt kopieren, wo es geht: das Extract liegt schon auf derselben
    # Platte, und Berlin sind knapp 100 MB.
    ln -f "$extract" "$dir/$name-latest.osm.pbf" 2>/dev/null \
        || cp "$extract" "$dir/$name-latest.osm.pbf"
    (cd "$dir" && md5sum "$name-latest.osm.pbf" > "$name-latest.osm.pbf.md5")
    echo "Spiegel: /$pfad/$name-latest.osm.pbf ($(wc -c < "$dir/$name-latest.osm.pbf") Bytes)"
done

tls="$ziel/tls"
openssl req -x509 -newkey rsa:2048 -nodes -days 2 \
    -subj "/CN=ConvoyPlan CI Geofabrik-Spiegel" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -keyout "$tls/ca.key" -out "$tls/ca.pem" 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=download.geofabrik.de" \
    -keyout "$tls/server.key" -out "$tls/server.csr" 2>/dev/null
printf '%s\n' "subjectAltName=DNS:download.geofabrik.de" \
    "extendedKeyUsage=serverAuth" "basicConstraints=CA:FALSE" > "$tls/server.ext"
openssl x509 -req -in "$tls/server.csr" -CA "$tls/ca.pem" -CAkey "$tls/ca.key" \
    -CAcreateserial -days 2 -extfile "$tls/server.ext" -out "$tls/server.pem" 2>/dev/null
# Der Schluessel der CA wird nach dem Signieren nicht mehr gebraucht.
rm -f "$tls/ca.key" "$tls/server.csr" "$tls/server.ext" "$tls/ca.srl"

# Die System-Wurzeln bleiben im Buendel: CURL_CA_BUNDLE ersetzt sie im
# Updater, und er spricht in diesem Job auch mit anderen Hosts.
system=""
for kandidat in /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt /etc/ssl/cert.pem; do
    [ -s "$kandidat" ] && { system="$kandidat"; break; }
done
{ [ -n "$system" ] && cat "$system"; cat "$tls/ca.pem"; } > "$tls/bundle.pem"
echo "Spiegel: Zertifikat fuer download.geofabrik.de, Buendel aus ${system:-nur Test-CA}"
