#!/usr/bin/env bash
# Prueft docker/updater/merge-extracts.sh gegen einen docker-Stub.
#
# Der Stub fuehrt kein osmium aus, sondern erzeugt eine Ergebnisdatei in einer
# vorgegebenen Groesse — so laesst sich die Plausibilitaetspruefung testen,
# ohne 400 MB Kartendaten zu bewegen. Geprueft wird: der Erfolgsfall, ein
# fehlgeschlagener Merge, ein stiller Teilmerge (zu klein) und ein Ergebnis
# groesser als die Rohsumme (nichts dedupliziert).
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../merge-extracts.sh"
FAILED=0

check() {
    if [ "$2" = "$3" ]; then
        echo "ok   — $1"
    else
        echo "FAIL — $1: erwartet '$3', bekam '$2'"
        FAILED=1
    fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/osm"

# Zwei Quellen zu je 1 MB -> Rohsumme 2 MB.
dd if=/dev/zero of="$TMP/osm/a-latest.osm.pbf" bs=1024 count=1024 2>/dev/null
dd if=/dev/zero of="$TMP/osm/b-latest.osm.pbf" bs=1024 count=1024 2>/dev/null
RAW=$(( 2 * 1024 * 1024 ))

# Der Stub liest MERGE_RESULT_BYTES und MERGE_EXIT aus der Umgebung.
cat > "$TMP/bin/docker" <<'STUB'
#!/usr/bin/env bash
echo "docker $*" >> "$DOCKER_CALLS"
[ "${MERGE_EXIT:-0}" -ne 0 ] && exit "$MERGE_EXIT"
# Zielpfad aus dem -o-Argument fischen und im Host-Verzeichnis anlegen.
out=""
prev=""
for a in "$@"; do
    [ "$prev" = "-o" ] && out="$a"
    prev="$a"
done
[ -n "$out" ] && dd if=/dev/zero of="$MERGE_OUT_DIR/$(basename "$out")" \
    bs=1 count="${MERGE_RESULT_BYTES:-0}" 2>/dev/null
exit 0
STUB
chmod +x "$TMP/bin/docker"
export PATH="$TMP/bin:$PATH" DOCKER_CALLS="$TMP/calls.txt" \
       MERGE_OUT_DIR="$TMP/osm" OSM_VOLUME="testproj_osm_data"

run_merge() {
    : > "$DOCKER_CALLS"
    rm -f "$TMP/osm/merged-test.osm.pbf"
    ( bash "$SCRIPT" "$TMP/osm/merged-test.osm.pbf" \
        "$TMP/osm/a-latest.osm.pbf" "$TMP/osm/b-latest.osm.pbf" >"$TMP/out.txt" 2>&1 )
    echo $?
}

# ── Fall 1: Erfolg — Ergebnis 99 % der Rohsumme (realistische Dedup) ────────
rc=$(MERGE_RESULT_BYTES=$(( RAW * 99 / 100 )) run_merge)
check "Erfolgsfall: Rueckgabewert 0" "$rc" "0"
[ -s "$TMP/osm/merged-test.osm.pbf" ] && r=ja || r=nein
check "Erfolgsfall: Zieldatei liegt vor" "$r" "ja"
grep -q "osmium merge" "$DOCKER_CALLS" && r=ja || r=nein
check "Erfolgsfall: osmium merge wurde aufgerufen" "$r" "ja"
grep -q "testproj_osm_data:/data/osm" "$DOCKER_CALLS" && r=ja || r=nein
check "Volume-NAME statt Containerpfad gemountet" "$r" "ja"
grep -q -- "--network none" "$DOCKER_CALLS" && r=ja || r=nein
check "Merge-Container bekommt kein Netzwerk" "$r" "ja"
grep -q "convoyplan/osmium" "$DOCKER_CALLS" && r=ja || r=nein
check "eigenes osmium-Image statt Fremdimage" "$r" "ja"
ls "$TMP/osm"/.merge-*.osm.pbf >/dev/null 2>&1 && r=ja || r=nein
check "Erfolgsfall: keine Temporaerdatei zurueckgeblieben" "$r" "nein"

# ── Fall 2: osmium scheitert ────────────────────────────────────────────────
rc=$(MERGE_EXIT=1 run_merge)
check "Fehlgeschlagener Merge: Rueckgabewert != 0" "$([ "$rc" -ne 0 ] && echo ja || echo nein)" "ja"
[ -e "$TMP/osm/merged-test.osm.pbf" ] && r=ja || r=nein
check "Fehlgeschlagener Merge: keine Zieldatei" "$r" "nein"

# ── Fall 3: stiller Teilmerge — Ergebnis nur 50 % der Rohsumme ─────────────
# Der gefaehrlichste Fall: eine formal gueltige Datei mit halbem Inhalt. Sie
# wuerde importieren, starten und an den fehlenden Stellen keine Route liefern.
# 40 % der Rohsumme = 0,8 MB, also weniger als die groesste Einzelquelle
# (1 MB) — nachweislich unvollstaendig.
rc=$(MERGE_RESULT_BYTES=$(( RAW * 40 / 100 )) run_merge)
check "Teilmerge wird abgelehnt" "$([ "$rc" -ne 0 ] && echo ja || echo nein)" "ja"
grep -qi "unplausibel" "$TMP/out.txt" && r=ja || r=nein
check "Teilmerge: Meldung nennt den Grund" "$r" "ja"
[ -e "$TMP/osm/merged-test.osm.pbf" ] && r=ja || r=nein
check "Teilmerge: keine Zieldatei zurueckgeblieben" "$r" "nein"

# ── Fall 4: groesser als die Rohsumme — nichts dedupliziert ────────────────
rc=$(MERGE_RESULT_BYTES=$(( RAW * 110 / 100 )) run_merge)
check "Ergebnis groesser als Rohsumme wird abgelehnt" "$([ "$rc" -ne 0 ] && echo ja || echo nein)" "ja"

# ── Fall 5: nur eine Quelle -> Fehler, Merge ergibt keinen Sinn ────────────
( bash "$SCRIPT" "$TMP/osm/x.osm.pbf" "$TMP/osm/a-latest.osm.pbf" >/dev/null 2>&1 )
check "eine einzige Quelle wird abgelehnt" "$([ $? -ne 0 ] && echo ja || echo nein)" "ja"

# ── Fall 6: starke Ueberlappung ist LEGITIM ────────────────────────────────
# Deutschland plus Bundeslaender dedupliziert auf etwa die Groesse
# Deutschlands. Eine Anteilsgrenze haette das faelschlich verworfen; die
# Untergrenze "groesste Einzelquelle" laesst es korrekt durch.
rc=$(MERGE_RESULT_BYTES=$(( RAW * 55 / 100 )) run_merge)
check "starke Ueberlappung wird akzeptiert" "$rc" "0"

# ── Fall 7: Kanten der Pruefung ────────────────────────────────────────────
rc=$(MERGE_RESULT_BYTES=$(( RAW / 2 )) run_merge)
check "exakt die groesste Einzelquelle besteht" "$rc" "0"
rc=$(MERGE_RESULT_BYTES=$(( RAW * 105 / 100 )) run_merge)
check "exakt 105 % der Rohsumme besteht" "$rc" "0"
rc=$(MERGE_RESULT_BYTES=$(( RAW * 106 / 100 )) run_merge)
check "106 % wird abgelehnt" "$([ "$rc" -ne 0 ] && echo ja || echo nein)" "ja"

# ── Fall 8: dieselbe Quelle zweimal ────────────────────────────────────────
# osmium wuerde sie klaglos mit sich selbst verschmelzen. Das Ergebnis haette
# die Groesse EINER Quelle — und bestuende damit die Untergrenze "groesste
# Einzelquelle", weil die groesste Einzelquelle eben diese eine ist. Keine
# Groessenpruefung kann das erkennen; sie muss vorher abgefangen werden.
: > "$DOCKER_CALLS"
( bash "$SCRIPT" "$TMP/osm/x.osm.pbf" \
    "$TMP/osm/a-latest.osm.pbf" "$TMP/osm/a-latest.osm.pbf" >"$TMP/out.txt" 2>&1 )
check "dieselbe Quelle zweimal wird abgelehnt" "$([ $? -ne 0 ] && echo ja || echo nein)" "ja"
grep -q "osmium merge" "$DOCKER_CALLS" && r=ja || r=nein
check "dabei wird osmium gar nicht erst gestartet" "$r" "nein"

# ── Fall 9: gleicher Dateiname aus verschiedenen Verzeichnissen ────────────
# Der Fall aus dem Geofabrik-Index: `europe/georgia` und
# `north-america/us/georgia`. Im Container liegen beide flach unter /data/osm —
# dort waeren sie DIESELBE Datei, ganz gleich wie verschieden ihre Pfade auf
# dem Host sind.
mkdir -p "$TMP/osm2"
dd if=/dev/zero of="$TMP/osm2/a-latest.osm.pbf" bs=1024 count=1024 2>/dev/null
: > "$DOCKER_CALLS"
( bash "$SCRIPT" "$TMP/osm/y.osm.pbf" \
    "$TMP/osm/a-latest.osm.pbf" "$TMP/osm2/a-latest.osm.pbf" >"$TMP/out.txt" 2>&1 )
check "gleicher Dateiname aus zwei Verzeichnissen wird abgelehnt" "$([ $? -ne 0 ] && echo ja || echo nein)" "ja"
grep -qi "dieselbe Datei" "$TMP/out.txt" && r=ja || r=nein
check "Meldung erklaert warum" "$r" "ja"

exit $FAILED
