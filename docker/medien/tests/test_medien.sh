#!/usr/bin/env bash
# Der Medien-Container gegen echte Handyvideos (docker/medien/tests/proben/):
# GPS-Position, Gerät und Aufnahmezeit sind danach weg, ein hochkant gedrehtes
# Video steht aufrecht, zu lange und kaputte werden abgelehnt, große werden
# auf 720p und 30 Bilder/s gebracht.
#
# Aufruf: MEDIEN_IMAGE=convoyplan-medien:ci bash docker/medien/tests/test_medien.sh
# Braucht Docker, curl und python3 auf dem Rechner, sonst nichts.
set -euo pipefail

IMAGE="${MEDIEN_IMAGE:-convoyplan-medien:ci}"
PROBEN="$(cd "$(dirname "$0")/proben" && pwd)"
NAME="medien-test-$$"
PORT="${MEDIEN_TEST_PORT:-18090}"
ARBEIT="$(mktemp -d)"
# ffprobe im Image läuft als uid 1001 und muss die Ergebnisse lesen.
chmod 755 "$ARBEIT"
FEHLER=0

aufraeumen() { docker rm -f "$NAME" >/dev/null 2>&1 || true; rm -rf "$ARBEIT"; }
trap aufraeumen EXIT

# Wie in compose: nur /tmp beschreibbar, kein Netz nach draußen nötig.
docker run -d --name "$NAME" --read-only --tmpfs /tmp:size=200m \
  -p "127.0.0.1:${PORT}:8090" "$IMAGE" >/dev/null
for _ in $(seq 1 30); do
  curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1 && break
  sleep 1
done

ok()   { echo "ok   $*"; }
nein() { echo "FEHL $*"; FEHLER=1; }

# Schickt eine Probe, legt Antwort (JSON) und das Video daraus ab. Gibt den HTTP-Code aus.
umwandeln() {
  local probe="$1" max="${2:-60}"
  curl -sS -o "$ARBEIT/$probe.json" -w '%{http_code}' \
    --data-binary "@$PROBEN/$probe" "http://127.0.0.1:${PORT}/video?max_sekunden=${max}"
}

feld() { python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])" "$1" "$2"; }

auspacken() {
  python3 - "$ARBEIT/$1.json" "$ARBEIT/$1.aus.mp4" "$ARBEIT/$1.poster.jpg" <<'PY'
import base64, json, sys
d = json.load(open(sys.argv[1]))
open(sys.argv[2], "wb").write(base64.b64decode(d["video"]))
open(sys.argv[3], "wb").write(base64.b64decode(d["poster"]))
PY
}

# ffprobe aus dem Image selbst, auf die Datei des Ergebnisses.
probe() {
  docker run --rm -v "$ARBEIT:/a:ro" --entrypoint ffprobe "$IMAGE" \
    -v error -print_format json -show_format -show_streams "/a/$1"
}

# ── GPS, Gerät, Aufnahmezeit ────────────────────────────────────────────────
code=$(umwandeln gps.mov)
[ "$code" = 200 ] && ok "gps.mov angenommen" || nein "gps.mov: HTTP $code $(cat "$ARBEIT/gps.mov.json")"
auspacken gps.mov
grep -aq "48.1374" "$PROBEN/gps.mov" || nein "Probe trägt keine Position — Test wäre wertlos"
for spur in "48.1374" "011.5755" "iPhone" "Apple" "2026-12-27" "ISO6709" "Lavf"; do
  if grep -aq -- "$spur" "$ARBEIT/gps.mov.aus.mp4"; then nein "Ausgabe enthält noch »$spur«"; else ok "ohne »$spur«"; fi
done
info=$(probe gps.mov.aus.mp4)
python3 - "$info" <<'PY' && ok "H.264/AAC, nur zwei Spuren, keine Tags" || nein "Format der Ausgabe"
import json, sys
d = json.loads(sys.argv[1])
arten = sorted(s["codec_type"] for s in d["streams"])
assert arten == ["audio", "video"], arten
v = next(s for s in d["streams"] if s["codec_type"] == "video")
assert v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p", v
assert next(s for s in d["streams"] if s["codec_type"] == "audio")["codec_name"] == "aac"
tags = d["format"].get("tags", {})
assert set(tags) <= {"major_brand", "minor_version", "compatible_brands"}, tags
for s in d["streams"]:
    assert set(s.get("tags", {})) <= {"language", "handler_name", "vendor_id"}, s.get("tags")
    assert not s.get("side_data_list"), s.get("side_data_list")
PY
[ "$(feld "$ARBEIT/gps.mov.json" ton)" = True ] && ok "Ton bleibt" || nein "Ton fehlt"
head -c 3 "$ARBEIT/gps.mov.poster.jpg" | od -An -tx1 | grep -q "ff d8 ff" && ok "Poster ist JPEG" || nein "Poster kein JPEG"

# ── Hochkant gedreht ────────────────────────────────────────────────────────
code=$(umwandeln hochkant.mov)
[ "$code" = 200 ] || nein "hochkant.mov: HTTP $code"
b=$(feld "$ARBEIT/hochkant.mov.json" breite); h=$(feld "$ARBEIT/hochkant.mov.json" hoehe)
[ "$b" -lt "$h" ] && ok "hochkant steht aufrecht (${b}×${h})" || nein "hochkant liegt (${b}×${h})"
auspacken hochkant.mov
probe hochkant.mov.aus.mp4 | grep -qi "rotation\|displaymatrix" && nein "Drehangabe noch drin" || ok "ohne Drehangabe"

# ── Groß und schnell → 720p, 30 Bilder/s, ohne Ton ─────────────────────────
code=$(umwandeln gross-stumm.mp4)
[ "$code" = 200 ] || nein "gross-stumm.mp4: HTTP $code"
b=$(feld "$ARBEIT/gross-stumm.mp4.json" breite); h=$(feld "$ARBEIT/gross-stumm.mp4.json" hoehe)
[ "$b" = 1280 ] && [ "$h" = 720 ] && ok "auf 1280×720" || nein "Größe ${b}×${h}"
[ "$(feld "$ARBEIT/gross-stumm.mp4.json" ton)" = False ] && ok "ohne Ton bleibt ohne Ton" || nein "Ton erfunden"
auspacken gross-stumm.mp4
fps=$(probe gross-stumm.mp4.aus.mp4 | python3 -c "import json,sys; v=[s for s in json.load(sys.stdin)['streams'] if s['codec_type']=='video'][0]; n,d=v['avg_frame_rate'].split('/'); print(round(int(n)/int(d)))")
[ "$fps" -le 30 ] && ok "${fps} Bilder/s" || nein "${fps} Bilder/s"

# ── Abgelehnt ───────────────────────────────────────────────────────────────
code=$(umwandeln lang.mp4)
[ "$code" = 422 ] && grep -q "länger als 60" "$ARBEIT/lang.mp4.json" && ok "65 s abgelehnt" || nein "lang.mp4: HTTP $code $(cat "$ARBEIT/lang.mp4.json")"
code=$(umwandeln lang.mp4 120)
[ "$code" = 200 ] && ok "mit höherer Grenze angenommen" || nein "lang.mp4 mit 120 s: HTTP $code"
code=$(umwandeln text.mp4)
[ "$code" = 422 ] && ok "Text abgelehnt" || nein "text.mp4: HTTP $code"
code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:${PORT}/anderes")
[ "$code" = 404 ] && ok "nur /video" || nein "/anderes: HTTP $code"

# Der Container hat danach nichts liegen lassen.
rest=$(docker exec "$NAME" sh -c 'find /tmp -mindepth 1 | wc -l')
[ "$rest" = 0 ] && ok "/tmp leer" || nein "/tmp: $rest Einträge übrig"

exit "$FEHLER"
